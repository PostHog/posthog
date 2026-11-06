import uuid
from pathlib import Path
from typing import cast

from django.conf import settings
from django.contrib import messages
from django.contrib.staticfiles import finders
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

import structlog

from posthog.admin.console.bridge import QueuedMessages
from posthog.admin.console.panels import Fact, Operation, Panel, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import ConsoleTool
from posthog.dataclasses import frozen
from posthog.git import get_git_commit_short
from posthog.models.team.team import Team
from posthog.models.user import User

logger = structlog.get_logger(__name__)

SEARCH_LIMIT = 25
RECENT_TEAMS_LIMIT = 8


@frozen
class RenderedPanel:
    panel: Panel
    facts: list[Fact]
    operations: list[Operation]


@frozen
class AttentionItem:
    """A warning or destructive fact, lifted to the top of the record page so staff see what is wrong first."""

    panel: Panel
    fact: Fact


ATTENTION_TONES = (Tone.WARNING, Tone.DESTRUCTIVE)


class ConsoleAssets:
    """A version for the console's CSS and JS URLs.

    Static files are served with a one-hour cache at fixed URLs, so without it a browser keeps the old
    stylesheet after a deploy or a rebuild and renders new markup unstyled.
    """

    @staticmethod
    def version() -> str:
        found = finders.find("admin-console/console.css")
        if isinstance(found, str):
            return str(Path(found).stat().st_mtime_ns)
        return get_git_commit_short() or ""


class ConsoleEnvironment:
    """Which deployment the console runs in. Each one gets its own tint, so open tabs are easy to tell apart."""

    LABELS = {"us": "US · production", "eu": "EU · production", "dev": "dev"}

    @staticmethod
    def key() -> str:
        deployment = (settings.CLOUD_DEPLOYMENT or "").upper()
        if deployment == "US":
            return "us"
        if deployment == "EU":
            return "eu"
        return "dev"

    @classmethod
    def context(cls) -> dict[str, object]:
        key = cls.key()
        tools_by_group: dict[str, list[ConsoleTool]] = {}
        for tool in console.tools():
            tools_by_group.setdefault(tool.group, []).append(tool)
        return {
            "console_env": key,
            "console_env_label": cls.LABELS[key],
            "console_tool_groups": tools_by_group,
            "console_asset_version": ConsoleAssets.version(),
        }


class RecentTeams:
    """The teams this staff member opened last, kept in the session, so the home page has somewhere to start."""

    SESSION_KEY = "admin_console_recent_teams"

    @classmethod
    def remember(cls, request: HttpRequest, team: Team) -> None:
        recent = [team_id for team_id in request.session.get(cls.SESSION_KEY, []) if team_id != team.pk]
        request.session[cls.SESSION_KEY] = [team.pk, *recent][:RECENT_TEAMS_LIMIT]

    @classmethod
    def load(cls, request: HttpRequest) -> list[Team]:
        team_ids: list[int] = request.session.get(cls.SESSION_KEY, [])
        if not team_ids:
            return []
        teams = Team.objects.select_related("organization").in_bulk(team_ids)
        return [teams[team_id] for team_id in team_ids if team_id in teams]


def _search_teams(query: str) -> list[Team]:
    if not query:
        return []
    teams = Team.objects.select_related("organization")
    if query.isdigit():
        return list(teams.filter(pk=int(query))[:1])
    # An exact token match uses the unique index. ORing it with the name scans below would scan the table for it too.
    by_token = list(teams.filter(api_token=query)[:1])
    if by_token:
        return by_token
    matches = teams.filter(Q(name__icontains=query) | Q(organization__name__icontains=query))
    return list(matches.order_by("-id")[:SEARCH_LIMIT])


def console_home(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    teams = _search_teams(query)
    if len(teams) == 1:
        if not query.isdigit():
            messages.info(request, f'Opened the only team that matches "{query}".')
        return redirect("admin_console_team", team_id=teams[0].pk)
    return render(
        request,
        "admin_console/home.html",
        {
            **ConsoleEnvironment.context(),
            "query": query,
            "teams": teams,
            "recent_teams": [] if query else RecentTeams.load(request),
            "tools": console.tools(),
            "team_panels": console.panels_for("team"),
        },
    )


def team_detail(request: HttpRequest, team_id: int) -> HttpResponse:
    team = get_object_or_404(Team.objects.select_related("organization"), pk=team_id)
    RecentTeams.remember(request, team)
    panels = [
        RenderedPanel(panel=panel, facts=panel.facts(team), operations=panel.operations(team))
        for panel in console.panels_for("team")
    ]
    return render(
        request,
        "admin_console/team.html",
        {
            **ConsoleEnvironment.context(),
            "team": team,
            "attention": [
                AttentionItem(panel=rendered.panel, fact=fact)
                for rendered in panels
                for fact in rendered.facts
                if fact.tone in ATTENTION_TONES
            ],
            "regular_panels": [rendered for rendered in panels if not rendered.panel.danger],
            "danger_panels": [rendered for rendered in panels if rendered.panel.danger],
        },
    )


def _is_offered(panel: Panel, team: Team, operation_key: str) -> bool:
    return any(operation.key == operation_key for operation in panel.operations(team))


def _find_operation(panel: Panel, team: Team, operation_key: str) -> Operation:
    # Look the operation up in what the panel offers now, so a stale form cannot run an operation the
    # current state no longer allows, for example suspending a team that is already suspended.
    for operation in panel.operations(team):
        if operation.key == operation_key:
            return operation
    raise Http404("This operation is not available for this team right now")


def run_team_operation(request: HttpRequest, team_id: int, panel_key: str, operation_key: str) -> HttpResponse:
    team = get_object_or_404(Team.objects.select_related("organization"), pk=team_id)
    panel = console.get_panel("team", panel_key)
    if panel is None:
        raise Http404("Unknown console panel")
    operation = _find_operation(panel, team, operation_key)
    team_url = reverse("admin_console_team", kwargs={"team_id": team.pk})

    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    if request.method == "GET" and operation.form_class is None:
        return redirect(team_url)

    form = None
    if operation.form_class is not None:
        form = operation.form_class(request.POST if request.method == "POST" else None, initial=operation.form_initial)
    context = {
        **ConsoleEnvironment.context(),
        "team": team,
        "panel": panel,
        "operation": operation,
        "form": form,
        # Handlers that move money or send messages build an idempotency key from it, so a double submit runs once.
        "form_nonce": request.POST.get("form_nonce") or str(uuid.uuid4()),
    }
    if request.method == "GET":
        return render(request, "admin_console/operation.html", context)
    if form is not None and not form.is_valid():
        return render(request, "admin_console/operation.html", context, status=400)

    audit = logger.bind(
        record="team",
        team_id=team.pk,
        panel=panel.key,
        operation=operation.key,
        reason=form.cleaned_data.get("reason") if form is not None else None,
        triggered_by=cast(User, request.user).email,
    )
    audit.info("admin_console_operation_started")
    response = operation.handler(request, team, form)
    audit.info("admin_console_operation_finished", status=response.status_code if response is not None else None)
    if response is None:
        return redirect(team_url)
    if response.status_code >= 400:
        team.refresh_from_db()
        # A handler can fail after its state change committed, for example when a notification fails.
        # The operation is then no longer offered, and staff belong on the team page, not on a dead form.
        if form is not None and _is_offered(panel, team, operation.key):
            return render(request, "admin_console/operation.html", context, status=400)
        if QueuedMessages.error_count(request) == 0:
            messages.error(
                request,
                f"{operation.label} failed with status {response.status_code}. The page below shows the current "
                f"state. Try again, or ask the {panel.owner.name} team if it keeps failing.",
            )
        return redirect(team_url)
    return response


def tool_page(request: HttpRequest, tool_key: str) -> HttpResponse:
    tool = console.get_tool(tool_key)
    if tool is None:
        raise Http404("Unknown console tool")
    page = tool.page(request)
    return render(
        request,
        "admin_console/tool.html",
        {**ConsoleEnvironment.context(), "tool": tool, "page": page},
    )


def append_slash(request: HttpRequest, rest: str) -> HttpResponse:
    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(f"/admin/console{rest}/" + (f"?{query}" if query else ""))

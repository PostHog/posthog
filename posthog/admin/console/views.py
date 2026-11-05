import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.staticfiles import finders
from django.db.models import Model, Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_safe

import structlog

from posthog.admin.console.bridge import QueuedMessages
from posthog.admin.console.panels import Fact, Operation, Panel, Tone
from posthog.admin.console.records import RECORD_TYPES, RecordLink, RecordType
from posthog.admin.console.registry import console
from posthog.admin.console.tools import ConsoleTool, Page, ToolOperation
from posthog.dataclasses import frozen
from posthog.git import get_git_commit_short
from posthog.models.team.team import Team
from posthog.models.user import User

logger = structlog.get_logger(__name__)

R = TypeVar("R")

SEARCH_LIMIT = 25
RECENT_TEAMS_LIMIT = 8


@frozen
class RenderedOperation:
    operation: Operation | ToolOperation
    url: str


@frozen
class RenderedPanel:
    panel: Panel
    facts: list[Fact]
    operations: list[RenderedOperation]


@frozen
class OperationTarget:
    """What an operation page acts on: a record, or a tool when the operation is not about one record."""

    kicker: str
    title: str
    badge: str
    subtitle: str
    back_url: str
    breadcrumbs: tuple[RecordLink, ...]
    # The submit button names a record ("Suspend for Acme"), so staff see which one they are about to change.
    is_record: bool


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
        return redirect("admin_console_team", pk=teams[0].pk)
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


def _record_type(record: str) -> RecordType:
    record_type = RECORD_TYPES.get(record)
    if record_type is None:
        raise Http404("Unknown console record type")
    return record_type


def _record_context(record_type: RecordType, obj: Model) -> dict[str, object]:
    return {
        **ConsoleEnvironment.context(),
        "record_type": record_type,
        "obj": obj,
        "record_title": record_type.title(obj),
        "record_subtitle": record_type.subtitle(obj),
        "record_url": record_type.url(obj),
        "record_parents": record_type.parents(obj),
    }


def record_detail(request: HttpRequest, record: str, pk: object) -> HttpResponse:
    record_type = _record_type(record)
    obj = get_object_or_404(record_type.queryset(), pk=pk)
    if isinstance(obj, Team):
        RecentTeams.remember(request, obj)
    panels = [
        RenderedPanel(
            panel=panel,
            facts=panel.facts(obj),
            operations=[
                RenderedOperation(
                    operation=operation,
                    url=reverse(
                        record_type.operation_url_name,
                        kwargs={"pk": obj.pk, "panel_key": panel.key, "operation_key": operation.key},
                    ),
                )
                for operation in panel.operations(obj)
            ],
        )
        for panel in console.panels_for(record_type.key)
    ]
    return render(
        request,
        "admin_console/record.html",
        {
            **_record_context(record_type, obj),
            "record_links": record_type.links(obj),
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


def _is_offered(panel: Panel, obj: Model, operation_key: str) -> bool:
    return any(operation.key == operation_key for operation in panel.operations(obj))


def _find_operation(panel: Panel, obj: Model, operation_key: str) -> Operation:
    # Look the operation up in what the panel offers now, so a stale form cannot run an operation the
    # current state no longer allows, for example suspending a team that is already suspended.
    for operation in panel.operations(obj):
        if operation.key == operation_key:
            return operation
    raise Http404("This operation is not available for this record right now")


def _audited(audit: structlog.BoundLogger, run: Callable[[], R]) -> R:
    audit.info("admin_console_operation_started")
    try:
        result = run()
    except Exception:
        audit.exception("admin_console_operation_crashed")
        raise
    status = result.status_code if isinstance(result, HttpResponse) else None
    audit.info("admin_console_operation_finished", status=status, result_page=isinstance(result, Page))
    return result


def _operation_context(
    target: OperationTarget, operation: Operation | ToolOperation, form: forms.Form | None, request: HttpRequest
) -> dict[str, object]:
    return {
        **ConsoleEnvironment.context(),
        "target": target,
        "operation": operation,
        "form": form,
        # Handlers that move money or send messages build an idempotency key from it, so a double submit runs once.
        "form_nonce": request.POST.get("form_nonce") or str(uuid.uuid4()),
    }


def run_operation(request: HttpRequest, record: str, pk: object, panel_key: str, operation_key: str) -> HttpResponse:
    record_type = _record_type(record)
    obj = get_object_or_404(record_type.queryset(), pk=pk)
    panel = console.get_panel(record_type.key, panel_key)
    if panel is None:
        raise Http404("Unknown console panel")
    operation = _find_operation(panel, obj, operation_key)
    record_url = record_type.url(obj)

    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    if request.method == "GET" and operation.form_class is None:
        return redirect(record_url)

    form = None
    if operation.form_class is not None:
        form = operation.form_class(request.POST if request.method == "POST" else None, initial=operation.form_initial)
    title = record_type.title(obj)
    target = OperationTarget(
        kicker="This acts on",
        title=title,
        badge=f"{record_type.label} {obj.pk}",
        subtitle=record_type.subtitle(obj),
        back_url=record_url,
        breadcrumbs=(
            *record_type.parents(obj),
            RecordLink(label=title, href=record_url),
            RecordLink(label=panel.title, href=f"{record_url}#panel-{panel.key}"),
        ),
        is_record=True,
    )
    context = _operation_context(target, operation, form, request)
    if request.method == "GET":
        return render(request, "admin_console/operation.html", context)
    if form is not None and not form.is_valid():
        return render(request, "admin_console/operation.html", context, status=400)

    audit = logger.bind(
        record=record_type.key,
        record_id=str(obj.pk),
        panel=panel.key,
        operation=operation.key,
        reason=form.cleaned_data.get("reason") if form is not None else None,
        triggered_by=cast(User, request.user).email,
    )
    response = _audited(audit, lambda: operation.handler(request, obj, form))
    if response is None:
        return redirect(record_url)
    if response.status_code >= 400:
        obj.refresh_from_db()
        # A handler can fail after its state change committed, for example when a notification fails.
        # The operation is then no longer offered, and staff belong on the record page, not on a dead form.
        if form is not None and _is_offered(panel, obj, operation.key):
            return render(request, "admin_console/operation.html", context, status=400)
        if QueuedMessages.error_count(request) == 0:
            messages.error(
                request,
                f"{operation.label} failed with status {response.status_code}. The page below shows the current "
                f"state. Try again, or ask the {panel.owner.name} team if it keeps failing.",
            )
        return redirect(record_url)
    return response


def _get_tool(tool_key: str) -> ConsoleTool:
    tool = console.get_tool(tool_key)
    if tool is None:
        raise Http404("Unknown console tool")
    return tool


def _with_query(url: str, request: HttpRequest) -> str:
    # A tool can have sub-pages picked by query parameters, so its operations and the way back keep them.
    query = request.META.get("QUERY_STRING", "")
    return url + (f"?{query}" if query else "")


@require_safe
def tool_page(request: HttpRequest, tool_key: str) -> HttpResponse:
    tool = _get_tool(tool_key)
    operations = [
        RenderedOperation(
            operation=operation,
            url=_with_query(
                reverse("admin_console_tool_operation", kwargs={"tool_key": tool.key, "operation_key": operation.key}),
                request,
            ),
        )
        for operation in tool.operations(request)
    ]
    return render(
        request,
        "admin_console/tool.html",
        {**ConsoleEnvironment.context(), "tool": tool, "page": tool.page(request), "operations": operations},
    )


def run_tool_operation(request: HttpRequest, tool_key: str, operation_key: str) -> HttpResponse:
    tool = _get_tool(tool_key)
    operation = next((op for op in tool.operations(request) if op.key == operation_key), None)
    if operation is None:
        raise Http404("This operation is not available right now")
    tool_url = _with_query(reverse("admin_console_tool", kwargs={"tool_key": tool.key}), request)

    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    if request.method == "GET" and operation.form_class is None:
        return redirect(tool_url)

    form = None
    if operation.form_class is not None:
        form = operation.form_class(request.POST if request.method == "POST" else None, initial=operation.form_initial)
    target = OperationTarget(
        kicker="This runs from",
        title=tool.title,
        badge=tool.group,
        subtitle=tool.description,
        back_url=tool_url,
        breadcrumbs=(RecordLink(label=tool.title, href=tool_url),),
        is_record=False,
    )
    context = _operation_context(target, operation, form, request)
    if request.method == "GET":
        return render(request, "admin_console/operation.html", context)
    if form is not None and not form.is_valid():
        return render(request, "admin_console/operation.html", context, status=400)

    audit = logger.bind(
        tool=tool.key,
        operation=operation.key,
        reason=form.cleaned_data.get("reason") if form is not None else None,
        triggered_by=cast(User, request.user).email,
    )
    result = _audited(audit, lambda: operation.handler(request, form))
    if result is None:
        return redirect(tool_url)
    if isinstance(result, Page):
        return render(request, "admin_console/result.html", {**context, "page": result})
    if result.status_code >= 400:
        if form is not None:
            return render(request, "admin_console/operation.html", context, status=400)
        if QueuedMessages.error_count(request) == 0:
            messages.error(request, f"{operation.label} failed with status {result.status_code}.")
        return redirect(tool_url)
    return result


def append_slash(request: HttpRequest, rest: str) -> HttpResponse:
    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(f"/admin/console{rest}/" + (f"?{query}" if query else ""))

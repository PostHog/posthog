import uuid
from typing import cast

from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

import structlog

from posthog.admin.console.panels import Fact, Operation, Panel
from posthog.admin.console.registry import console
from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User

logger = structlog.get_logger(__name__)

SEARCH_LIMIT = 25


@frozen
class RenderedPanel:
    panel: Panel
    facts: list[Fact]
    operations: list[Operation]


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
    def context(cls) -> dict[str, str]:
        key = cls.key()
        return {"console_env": key, "console_env_label": cls.LABELS[key]}


def _search_teams(query: str) -> list[Team]:
    if not query:
        return []
    if query.isdigit():
        return list(Team.objects.filter(pk=int(query)).select_related("organization")[:1])
    matches = Team.objects.filter(
        Q(api_token=query) | Q(name__icontains=query) | Q(organization__name__icontains=query)
    ).select_related("organization")
    return list(matches.order_by("-id")[:SEARCH_LIMIT])


def console_home(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    teams = _search_teams(query)
    if query.isdigit() and len(teams) == 1:
        return redirect("admin_console_team", team_id=teams[0].pk)
    return render(
        request,
        "admin_console/home.html",
        {**ConsoleEnvironment.context(), "query": query, "teams": teams},
    )


def team_detail(request: HttpRequest, team_id: int) -> HttpResponse:
    team = get_object_or_404(Team.objects.select_related("organization"), pk=team_id)
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
            "regular_panels": [rendered for rendered in panels if not rendered.panel.danger],
            "danger_panels": [rendered for rendered in panels if rendered.panel.danger],
        },
    )


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
        form = operation.form_class(request.POST if request.method == "POST" else None)
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
        messages.error(request, f"{operation.label} failed with status {response.status_code}.")
        return redirect(team_url)
    return response

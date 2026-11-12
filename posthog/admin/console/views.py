import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.staticfiles import finders
from django.core.exceptions import PermissionDenied
from django.db.models import Model, Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.datastructures import MultiValueDict
from django.views.decorators.http import require_GET, require_safe

import structlog

from posthog.admin.console.bridge import QueuedMessages
from posthog.admin.console.confirm import ConfirmationToken
from posthog.admin.console.panels import Fact, Gate, Operation, Owner, Panel, Tone
from posthog.admin.console.records import RECORD_TYPES, SUPPORT_TICKET_PARAM, RecordLink, RecordType
from posthog.admin.console.registry import console
from posthog.admin.console.results import OperationResult, OperationResults, ResultState
from posthog.admin.console.tools import ConsoleTool, Page, ToolOperation
from posthog.dataclasses import frozen
from posthog.git import get_git_commit_short
from posthog.helpers.email_utils import EmailLookupHandler
from posthog.models.organization import Organization
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
    # The operation's gate, with Gate.owner() resolved to the staff group of the panel or tool owner.
    gate: Gate | None
    # False when the gate keeps this staff member out. The page shows it disabled, with who may run it.
    allowed: bool


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


def _with_kept_query(url: str, request: HttpRequest, names: tuple[str, ...]) -> str:
    kept = [(name, value) for name in names for value in request.GET.getlist(name)]
    return f"{url}?{urlencode(kept)}" if kept else url


def _find_user(query: str) -> User | None:
    # Team and organization names rarely hold an @, so a query with one is an email address and opens that user.
    if "@" not in query:
        return None
    return EmailLookupHandler.get_user_by_email(query, is_active=None)


def _as_uuid(query: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(query)
    except ValueError:
        return None


def _find_by_uuid(record_id: uuid.UUID) -> HttpResponse | None:
    # Both lookups hit a unique index: the organization primary key, then the team UUID.
    organization = Organization.objects.filter(pk=record_id).only("pk").first()
    if organization is not None:
        return redirect("admin_console_organization", pk=organization.pk)
    team = Team.objects.filter(uuid=record_id).only("pk").first()
    return redirect("admin_console_team", pk=team.pk) if team is not None else None


def console_home(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    user = _find_user(query)
    if user is not None:
        return HttpResponseRedirect(
            _with_kept_query(reverse("admin_console_user", kwargs={"pk": user.pk}), request, (SUPPORT_TICKET_PARAM,))
        )
    record_id = _as_uuid(query)
    if record_id is not None:
        found = _find_by_uuid(record_id)
        if found is not None:
            return found
        # A project API token can have the form of a UUID, and the token match uses a unique index.
        # A UUID is never a name, so the name scan across every team stays skipped.
        teams = list(Team.objects.select_related("organization").filter(api_token=query)[:1])
    else:
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


def _gate(operation: Operation | ToolOperation, owner: Owner) -> Gate | None:
    return operation.gate.resolve(owner) if operation.gate is not None else None


def _rendered_operation(
    request: HttpRequest, operation: Operation | ToolOperation, owner: Owner, url: str
) -> RenderedOperation:
    gate = _gate(operation, owner)
    return RenderedOperation(operation=operation, url=url, gate=gate, allowed=gate is None or gate.allows(request))


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
                _rendered_operation(
                    request,
                    operation,
                    panel.owner,
                    reverse(
                        record_type.operation_url_name,
                        kwargs={"pk": obj.pk, "panel_key": panel.key, "operation_key": operation.key},
                    ),
                )
                for operation in _offered_operations(panel, obj)
            ],
        )
        for panel in console.panels_for(record_type.key)
    ]
    return render(
        request,
        "admin_console/record.html",
        {
            **_record_context(record_type, obj),
            "record_links": [
                RecordLink(
                    label=link.label,
                    href=_with_kept_query(link.href, request, link.keep_query),
                    title=link.title,
                )
                for link in record_type.links(obj)
            ],
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


def _offered_operations(panel: Panel, obj: Model) -> list[Operation]:
    operations = panel.operations(obj)
    if panel.operation_keys is not None:
        undeclared = sorted({operation.key for operation in operations} - panel.operation_keys)
        if undeclared:
            raise ValueError(f"Console panel {panel.key!r} offers operations missing from operation_keys: {undeclared}")
    return operations


def _is_offered(panel: Panel, obj: Model, operation_key: str) -> bool:
    return any(operation.key == operation_key for operation in _offered_operations(panel, obj))


def _find_operation(panel: Panel, obj: Model, operation_key: str) -> Operation:
    # Look the operation up in what the panel offers now, so a stale form cannot run an operation the
    # current state no longer allows, for example suspending a team that is already suspended.
    for operation in _offered_operations(panel, obj):
        if operation.key == operation_key:
            return operation
    raise Http404("This operation is not available for this record right now")


def _require_gate(
    request: HttpRequest, operation: Operation | ToolOperation, owner: Owner, audit: structlog.BoundLogger
) -> None:
    # The page only disables the button. This check is the one that keeps a hand-built request out.
    gate = _gate(operation, owner)
    if gate is not None and not gate.allows(request):
        audit.warning("admin_console_operation_denied", method=request.method)
        raise PermissionDenied(f"Only {gate.label} can run {operation.label}")


# Query keys that name what a tool operation acts on, such as a record, a health check or an ingestion
# pipeline. Other values can hold customer data, for example a TopHog distinct ID that is an email
# address, so the audit log keeps only their key.
AUDITED_QUERY_KEYS = frozenset(
    {
        "check",
        "id",
        "organization",
        "organization_id",
        "pipelines",
        "project",
        "project_id",
        "schema",
        "source",
        "team",
        "team_id",
        "token",
        "user",
        "user_id",
    }
)


def _audit_query(request: HttpRequest) -> dict[str, str]:
    return {key: request.GET.get(key, "") if key in AUDITED_QUERY_KEYS else "<not logged>" for key in request.GET}


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
        # Templates call callables, so the preview handler cannot be tested there directly.
        "has_preview": getattr(operation, "preview", None) is not None,
        # Handlers that move money or send messages build an idempotency key from it, so a double submit runs once.
        "form_nonce": request.POST.get("form_nonce") or str(uuid.uuid4()),
    }


class ConfirmStep:
    """The form data an operation runs with: the submitted form, or the input a confirmed preview showed."""

    def __init__(self, request: HttpRequest, confirmation: ConfirmationToken) -> None:
        self.confirmation = confirmation
        self.token = request.POST.get("confirm_token") if request.method == "POST" else None
        self.data: QueryDict | None = None
        self.files: MultiValueDict | None = None
        if self.token is not None:
            confirmed = confirmation.load(self.token)
            if confirmed is not None:
                self.data, self.files = confirmed.data, confirmed.files
        elif request.method == "POST":
            self.data, self.files = request.POST, request.FILES

    @property
    def confirmed(self) -> bool:
        return self.token is not None

    @property
    def expired(self) -> bool:
        return self.confirmed and self.data is None

    def bind(self, operation: Operation | ToolOperation, initial: dict[str, object] | None = None) -> forms.Form | None:
        if operation.form_class is None:
            return None
        return operation.form_class(self.data, self.files, initial=initial or operation.form_initial)

    def render_expired(self, request: HttpRequest) -> HttpResponse:
        messages.error(request, "This confirmation expired or was made for something else. Review the change again.")
        return redirect(request.get_full_path())

    def render_preview(
        self, request: HttpRequest, context: dict[str, object], form: forms.Form, preview: Callable[[], Page]
    ) -> HttpResponse:
        page = preview().refuse_secrets("preview")
        if form.errors:
            return render(request, "admin_console/operation.html", context, status=400)
        return render(
            request,
            "admin_console/confirm.html",
            {**context, "page": page, "confirm_token": self.confirmation.sign(form)},
        )


def _no_store(response: HttpResponse) -> HttpResponse:
    add_never_cache_headers(response)
    return response


def _show_result(
    request: HttpRequest, operation: Operation | ToolOperation, target: OperationTarget, page: Page
) -> HttpResponse:
    result = OperationResult(
        actor_id=cast(User, request.user).pk, operation_label=operation.label, target=target, page=page
    )
    try:
        return _no_store(OperationResults.redirect_to(result))
    except Exception:
        # The operation already ran, and its result may hold a password that the control plane returns only
        # once. When the result cannot be stored, this response is the only way left to show it, so the page
        # renders here, at the cost that a reload would submit the form again.
        logger.exception("admin_console_result_handoff_failed", operation=operation.key)
        context = {**ConsoleEnvironment.context(), "result": result}
        return _no_store(render(request, "admin_console/result.html", context))


@require_GET
def operation_result(request: HttpRequest, result_id: str) -> HttpResponse:
    """The result page of an operation that ran. It shows once, so a reload never runs the operation again."""
    read = OperationResults.take(request, result_id)
    context = {**ConsoleEnvironment.context(), "result": read.result, "state": read.state}
    response = render(request, "admin_console/result.html", context, status=200 if read.result else 410)
    if read.state != ResultState.KEY_MISSING:
        OperationResults.forget_key(response, result_id)
    return _no_store(response)


def _record_form_initial(request: HttpRequest, operation: Operation) -> dict[str, object] | None:
    # A link preselects a choice, so an old URL that names one of several documents opens the form on it.
    # Text fields stay empty: a reason taken from a URL would reach the audit log without staff writing it.
    if operation.form_class is None:
        return None
    preselected = {
        name: request.GET[name]
        for name, field in operation.form_class.base_fields.items()
        if isinstance(field, forms.ChoiceField) and name in request.GET
    }
    if not preselected:
        return operation.form_initial
    return {**(operation.form_initial or {}), **preselected}


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
    audit = logger.bind(
        record=record_type.key,
        record_id=str(obj.pk),
        panel=panel.key,
        operation=operation.key,
        triggered_by=cast(User, request.user).email,
    )
    _require_gate(request, operation, panel.owner, audit)
    if request.method == "GET" and operation.form_class is None:
        return redirect(record_url)

    # The panel is part of the target, so a confirmation for one record or panel cannot confirm another.
    step = ConfirmStep(request, ConfirmationToken(request, f"{record_type.key}:{obj.pk}:{panel.key}", operation.key))
    if step.expired:
        return step.render_expired(request)
    form = step.bind(operation, initial=_record_form_initial(request, operation))
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

    preview = operation.preview
    if preview is not None and form is not None and not step.confirmed:
        return step.render_preview(request, context, form, lambda: preview(request, obj, form))

    audit = audit.bind(reason=form.cleaned_data.get("reason") if form is not None else None)
    response = _audited(audit, lambda: operation.handler(request, obj, form))
    if not isinstance(response, HttpResponse) or response.status_code < 400:
        step.confirmation.discard_uploads()
    if response is None:
        return redirect(record_url)
    if isinstance(response, Page):
        return _show_result(request, operation, target, response)
    if response.status_code >= 400:
        obj.refresh_from_db()
        # A handler can fail after its state change committed, for example when a notification fails.
        # The operation is then no longer offered, and staff belong on the record page, not on a dead form.
        if form is not None and _is_offered(panel, obj, operation.key):
            return render(request, "admin_console/operation.html", context, status=response.status_code)
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


def _query_suffix(request: HttpRequest) -> str:
    query = request.META.get("QUERY_STRING", "")
    return f"?{query}" if query else ""


def _with_query(url: str, request: HttpRequest) -> str:
    # A tool can have sub-pages picked by query parameters, so its operations, live blocks and the way back keep them.
    return url + _query_suffix(request)


@require_safe
def tool_page(request: HttpRequest, tool_key: str) -> HttpResponse:
    tool = _get_tool(tool_key)
    app_response = tool.app_page(request)
    if app_response is not None:
        return app_response
    operations = [
        _rendered_operation(
            request,
            operation,
            tool.owner,
            _with_query(
                reverse("admin_console_tool_operation", kwargs={"tool_key": tool.key, "operation_key": operation.key}),
                request,
            ),
        )
        for operation in tool.operations(request)
    ]
    return render(
        request,
        "admin_console/tool.html",
        {
            **ConsoleEnvironment.context(),
            "tool": tool,
            "page": tool.page(request).refuse_secrets("tool page"),
            "operations": operations,
            "query_suffix": _query_suffix(request),
        },
    )


@require_safe
def tool_live(request: HttpRequest, tool_key: str, live_key: str) -> HttpResponse:
    """One live block of a tool page, for console.js to swap in. It reads only, like the page itself."""
    tool = _get_tool(tool_key)
    live = tool.live(request, live_key)
    if live is None:
        raise Http404("Unknown live block")
    live_url = _with_query(
        reverse("admin_console_tool_live", kwargs={"tool_key": tool.key, "live_key": live.key}), request
    )
    response = render(request, "admin_console/_live.html", {"tool": tool, "live": live, "live_url": live_url})
    # console.js swaps in only a response that carries this header, never a login page or an error page.
    response["X-Console-Live"] = "1"
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def tool_download(request: HttpRequest, tool_key: str, download_key: str) -> HttpResponse:
    """A file a tool hands staff. It reads only, like the tool page that links to it."""
    download = _get_tool(tool_key).download(request, download_key)
    if download is None:
        raise Http404("Unknown download")
    response = HttpResponse(download.content, content_type=download.content_type)
    response["Content-Disposition"] = f'attachment; filename="{download.filename}"'
    response["Cache-Control"] = "no-store"
    return response


def run_tool_operation(request: HttpRequest, tool_key: str, operation_key: str) -> HttpResponse:
    tool = _get_tool(tool_key)
    operation = next((op for op in tool.operations(request) if op.key == operation_key), None)
    if operation is None:
        raise Http404("This operation is not available right now")
    tool_url = _with_query(reverse("admin_console_tool", kwargs={"tool_key": tool.key}), request)

    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    audit = logger.bind(
        tool=tool.key,
        operation=operation.key,
        query=_audit_query(request),
        triggered_by=cast(User, request.user).email,
    )
    _require_gate(request, operation, tool.owner, audit)
    if request.method == "GET" and operation.form_class is None:
        return redirect(tool_url)

    target = OperationTarget(
        kicker="This runs from",
        title=tool.title,
        badge=tool.group,
        subtitle=tool.description,
        back_url=tool_url,
        breadcrumbs=(RecordLink(label=tool.title, href=tool_url),),
        is_record=False,
    )
    step = ConfirmStep(request, ConfirmationToken(request, f"tool:{tool.key}", operation.key))
    if step.expired:
        return step.render_expired(request)

    form = step.bind(operation)
    context = _operation_context(target, operation, form, request)
    if request.method == "GET":
        return render(request, "admin_console/operation.html", context)
    if form is not None and not form.is_valid():
        return render(request, "admin_console/operation.html", context, status=400)

    preview = operation.preview
    if preview is not None and form is not None and not step.confirmed:
        return step.render_preview(request, context, form, lambda: preview(request, form))

    audit = audit.bind(reason=form.cleaned_data.get("reason") if form is not None else None)
    result = _audited(audit, lambda: operation.handler(request, form))
    if not isinstance(result, HttpResponse) or result.status_code < 400:
        step.confirmation.discard_uploads()
    if result is None:
        return redirect(tool_url)
    if isinstance(result, Page):
        return _show_result(request, operation, target, result)
    if result.status_code >= 400:
        if form is not None:
            return render(request, "admin_console/operation.html", context, status=result.status_code)
        if QueuedMessages.error_count(request) == 0:
            messages.error(request, f"{operation.label} failed with status {result.status_code}.")
        return redirect(tool_url)
    return result


def append_slash(request: HttpRequest, rest: str) -> HttpResponse:
    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(f"/admin/console{rest}/" + (f"?{query}" if query else ""))

from collections.abc import Iterable

from django.db.models import Q, QuerySet
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.scopes import clamp_scopes_to_ceiling, scopes_not_covered

# What a step-up app gets on its first connection to the MCP resource. The list comes from MCP
# tool usage: a scope is in when the tools that need it are among the ones most OAuth users call,
# so most sessions never need a step-up. Organization and user stay read-only. `project:write` is
# in because routine project setup (replay sampling, test account filters, cookieless mode) would
# otherwise send many users to a step-up. `endpoint:write` is in for pushing endpoints from the
# CLI. A write scope covers its read, so no object appears twice. Anything else arrives through
# step-up when a tool first needs it.
STEP_UP_DEFAULT_RESOURCE_SCOPES: frozenset[str] = frozenset(
    [
        *(
            f"{scope_object}:write"
            for scope_object in (
                "action",
                "alert",
                "annotation",
                "cohort",
                "dashboard",
                "data_catalog",
                "endpoint",
                "error_tracking",
                "event_definition",
                "experiment",
                "external_data_source",
                "feature_flag",
                "heatmap",
                "hog_flow",
                "hog_function",
                "insight",
                "insight_variable",
                "llm_skill",
                "marketing_analytics",
                "notebook",
                "person",
                "product_enablement",
                "project",
                "property_definition",
                "replay_scanner",
                "session_recording_playlist",
                "signal_scout",
                "subscription",
                "survey",
                "task",
                "warehouse_view",
            )
        ),
        *(
            f"{scope_object}:read"
            for scope_object in (
                "activity_log",
                "batch_export",
                "billing",
                "business_knowledge",
                "dashboard_template",
                "early_access_feature",
                "evaluation",
                "experiment_saved_metric",
                "group",
                "health_issue",
                "integration",
                "llm_prompt",
                "logs",
                "mcp_analytics",
                "organization",
                "organization_member",
                "query",
                "session_recording",
                "ticket",
                "tracing",
                "user",
                "warehouse_table",
                "web_analytics",
            )
        ),
    ]
)


@frozen
class GrantAccess:
    scoped_teams: list[int]
    scoped_organizations: list[str]
    """Both lists empty means the grant reaches everything the user can reach."""


@frozen
class StepUpGrant:
    scopes: list[str]
    """What the grant carries, which the consent screen lists in full."""
    already_granted_scopes: list[str]
    """Scopes of the grant this user granted the app before, which the screen shows as granted."""
    earlier_access: GrantAccess | None
    """Where the newest earlier grant applies. The consent screen pre-selects it, so a step-up keeps the token's projects."""


def resolve_step_up_grant(
    *, requested: Iterable[str], application: OAuthApplication, user_id: int, required: Iterable[str]
) -> StepUpGrant:
    """Scopes for an MCP authorization by an app that supports step-up.

    A first connection gets the request narrowed to the default set. A step-up keeps every scope
    this user already granted this app and adds the request, with no cap: some clients
    re-authorize with only the challenged scopes, and they must not lose what they had.
    """
    requested = list(requested)
    granted = live_granted_scopes(application=application, user_id=user_id)
    if granted is None:
        narrowed = narrow_to_step_up_default(requested)
        # A request with nothing in the default set is already narrow. Narrowing it to identity
        # scopes alone would only force a second consent for the scope it asked for.
        if not any(":" in scope for scope in narrowed):
            narrowed = requested
        return StepUpGrant(scopes=sorted(_union(narrowed, required)), already_granted_scopes=[], earlier_access=None)

    # The ceiling may have shrunk since an older grant. Clamp as `validate_scopes` does, so the
    # screen never promises a scope the new grant cannot carry.
    granted = set(clamp_scopes_to_ceiling(granted, application.ceiling_scopes, allow_wildcard_under_empty_ceiling=True))
    scopes = sorted(_union(granted, requested, required))
    already_granted = [scope for scope in scopes if not scopes_not_covered(granted, [scope])]
    return StepUpGrant(
        scopes=scopes,
        already_granted_scopes=already_granted,
        earlier_access=newest_live_grant_access(application=application, user_id=user_id),
    )


def narrow_to_step_up_default(requested: Iterable[str]) -> list[str]:
    narrowed: list[str] = []
    for scope in requested:
        if scope == "*":
            narrowed.extend(sorted(STEP_UP_DEFAULT_RESOURCE_SCOPES))
        elif ":" not in scope or not scopes_not_covered(STEP_UP_DEFAULT_RESOURCE_SCOPES, [scope]):
            narrowed.append(scope)
        elif scope.endswith(":write"):
            read_scope = f"{scope.removesuffix(':write')}:read"
            if not scopes_not_covered(STEP_UP_DEFAULT_RESOURCE_SCOPES, [read_scope]):
                narrowed.append(read_scope)
    return _union(narrowed)


def live_granted_scopes(*, application: OAuthApplication, user_id: int) -> set[str] | None:
    """Every scope this user granted this app on a grant that still works, or None when there is none.

    A grant works while its access token is unexpired or its refresh token is unrevoked. The refresh
    token outlives the access token, so a client whose access token expired still counts as
    connected and keeps its scopes. Tokens minted during staff impersonation are left out, because
    the user did not grant those.
    """
    granted: set[str] | None = None
    for scope_string in _live_access_tokens(application, user_id).values_list("scope", flat=True):
        granted = (granted or set()) | set((scope_string or "").split())
    return granted


def newest_live_grant_access(*, application: OAuthApplication, user_id: int) -> GrantAccess | None:
    newest = (
        _live_access_tokens(application, user_id)
        .order_by("-created")
        .values("scoped_teams", "scoped_organizations")
        .first()
    )
    if newest is None:
        return None
    return GrantAccess(
        scoped_teams=list(newest["scoped_teams"] or []),
        scoped_organizations=[str(org) for org in newest["scoped_organizations"] or []],
    )


def _live_access_tokens(application: OAuthApplication, user_id: int) -> QuerySet[OAuthAccessToken]:
    return OAuthAccessToken.objects.filter(
        application=application, user_id=user_id, impersonated_by__isnull=True
    ).filter(Q(expires__gt=timezone.now()) | Q(refresh_token__isnull=False, refresh_token__revoked__isnull=True))


def _union(*scope_lists: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(scope for scopes in scope_lists for scope in scopes))

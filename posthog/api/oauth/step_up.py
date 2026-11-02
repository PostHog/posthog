from collections.abc import Iterable

from django.db.models import Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.scopes import scopes_not_covered

# What a step-up app gets on its first connection to the MCP resource. A write scope covers
# its read, so no object appears twice.
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
class StepUpGrant:
    scopes: list[str]
    """What the grant carries."""
    consent_scopes: list[str]
    """What the consent screen lists: the whole grant on a first connection, only the added scopes on a step-up."""
    hidden_scopes: list[str]
    """Scopes of the grant the consent screen leaves out, because the user granted them before."""


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
        scopes = sorted(_union(narrowed, required))
        return StepUpGrant(scopes=scopes, consent_scopes=scopes, hidden_scopes=[])

    scopes = sorted(_union(granted, requested, required))
    added = [scope for scope in scopes if scopes_not_covered(granted, [scope])]
    if not added:
        # An empty list would render no permissions and submit a blank scope, so a request that
        # adds nothing shows what the grant already holds.
        return StepUpGrant(scopes=scopes, consent_scopes=scopes, hidden_scopes=[])
    return StepUpGrant(
        scopes=scopes, consent_scopes=added, hidden_scopes=[scope for scope in scopes if scope not in added]
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
    scope_strings = (
        OAuthAccessToken.objects.filter(application=application, user_id=user_id, impersonated_by__isnull=True)
        .filter(Q(expires__gt=timezone.now()) | Q(refresh_token__isnull=False, refresh_token__revoked__isnull=True))
        .values_list("scope", flat=True)
    )
    granted: set[str] | None = None
    for scope_string in scope_strings:
        granted = (granted or set()) | set((scope_string or "").split())
    return granted


def _union(*scope_lists: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(scope for scopes in scope_lists for scope in scopes))

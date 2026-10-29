"""
Per-user cache of the TeamSerializer output that the logged-in app page boots with.

The key holds a per-team version and the org serializer version. Writes to the team and to its
config rows bump the team version. The org serializer version already moves on organization,
membership, role and access control writes, which decide the user's access fields. Writes that skip Django
signals rely on TEAM_APP_CONTEXT_CACHE_TTL_SECONDS as the staleness bound. The receivers must
connect at django.setup(), so PostHogConfig.ready() imports this module.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models.signals import post_delete, post_save

from opentelemetry import trace

from posthog.caching.cache_version import bump_cache_version, read_cache_version
from posthog.caching.organization_serializer_cache import _org_serializer_cache_version
from posthog.utils import get_safe_cache, safe_cache_set

if TYPE_CHECKING:
    from posthog.api.team.team_serializer import TeamSerializer
    from posthog.models.team import Team

TEAM_APP_CONTEXT_CACHE_TTL_SECONDS = 10 * 60
TEAM_CACHE_VERSION_TTL_SECONDS = 24 * 60 * 60

# Built on every request: each one is minted per request or reads its own cache.
PER_REQUEST_FIELDS = ("live_events_token", "group_types", "has_group_types", "product_intents", "flag_evaluations_mode")


def _team_cache_version_key(team_id: int) -> str:
    return f"team_app_context_version:{team_id}"


def _team_cache_version(team_id: int) -> int:
    return read_cache_version(_team_cache_version_key(team_id), TEAM_CACHE_VERSION_TTL_SECONDS)


def bump_team_cache_version(team_id: int) -> None:
    bump_cache_version(_team_cache_version_key(team_id), TEAM_CACHE_VERSION_TTL_SECONDS)


def cached_team_app_context(serializer: "TeamSerializer", team: "Team", user_id: int) -> dict[str, Any]:
    # Ingestion sets ingested_event with raw SQL, so no signal would clear an entry built before the
    # first event, and onboarding would wait for the TTL.
    if not team.ingested_event:
        return serializer.data
    team_version = _team_cache_version(team.pk)
    org_version = _org_serializer_cache_version(str(team.organization_id))
    cache_key = f"team_app_context:{team.pk}:t{team_version}:o{org_version}:{user_id}"
    cached = get_safe_cache(cache_key)
    trace.get_current_span().set_attribute("app_context.team_cache_hit", cached is not None)
    if cached is None:
        data = serializer.data
        safe_cache_set(
            cache_key,
            {field: value for field, value in data.items() if field not in PER_REQUEST_FIELDS},
            timeout=TEAM_APP_CONTEXT_CACHE_TTL_SECONDS,
        )
        return data
    return {**cached, **{field: getattr(serializer, f"get_{field}")(team) for field in PER_REQUEST_FIELDS}}


_INVALIDATION_SOURCES: list[tuple[str, Callable[[Any], int | None]]] = [
    ("posthog.Team", lambda instance: instance.pk),
    ("posthog.TeamRevenueAnalyticsConfig", lambda instance: instance.team_id),
    ("posthog.TeamMarketingAnalyticsConfig", lambda instance: instance.team_id),
    ("customer_analytics.TeamCustomerAnalyticsConfig", lambda instance: instance.team_id),
    ("workflows.TeamWorkflowsConfig", lambda instance: instance.team_id),
    ("feature_flags.TeamFeatureFlagPolicyConfig", lambda instance: instance.team_id),
    ("data_modeling.DataWarehouseManagedViewSet", lambda instance: instance.team_id),
    ("posthog.TeamHeatmapConfig", lambda instance: instance.team_id),
    ("dashboards.TeamHomeTabDashboardConfig", lambda instance: instance.team_id),
]


def _connect_invalidation(model_label: str, get_team_id: Callable[[Any], int | None]) -> None:
    def receiver_fn(sender: Any, instance: Any, **kwargs: Any) -> None:
        team_id = get_team_id(instance)
        if team_id is None:
            return
        # Bump again after commit, so a read between the write and the commit cannot cache the old row.
        bump_team_cache_version(team_id)
        transaction.on_commit(lambda: bump_team_cache_version(team_id))

    post_save.connect(receiver_fn, sender=model_label, weak=False)
    post_delete.connect(receiver_fn, sender=model_label, weak=False)


for _model_label, _resolver in _INVALIDATION_SOURCES:
    _connect_invalidation(_model_label, _resolver)

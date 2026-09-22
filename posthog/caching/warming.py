import itertools
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Optional

from django.db.models import Q

import structlog
import posthoganalytics
from celery import shared_task
from celery.canvas import chain
from prometheus_client import Counter, Gauge

from posthog.hogql.errors import ExposedHogQLError, TableAccessDeniedError

from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.caching.utils import largest_teams
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import Feature, get_team_query_tags, tag_queries
from posthog.dataclasses import frozen
from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.event_usage import EventSource
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.ph_client import ph_scoped_capture
from posthog.query_cache.freshness_index import clean_up_stale_insights, get_stale_insights
from posthog.query_creator_access import creator_access_revoked, report_creator_access_revoked
from posthog.schema_migrations.upgrade_manager import upgrade_insight
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue
from posthog.utils import variables_override_requested_by_client

from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.api import insight_variables_for_team, with_last_viewed_at
from products.product_analytics.backend.facade.models import Insight

logger = structlog.get_logger(__name__)

STALE_INSIGHTS_GAUGE = Gauge(
    "posthog_cache_warming_stale_insights_gauge",
    "Number of stale insights present",
    ["team_id"],
    multiprocess_mode="max",
)
PRIORITY_INSIGHTS_COUNTER = Counter(
    "posthog_cache_warming_priority_insights",
    "Number of priority insights warmed",
    ["team_id", "dashboard", "is_cached", "admission_reason"],
)

LAST_VIEWED_THRESHOLD = timedelta(days=7)
SHARED_INSIGHTS_LAST_VIEWED_THRESHOLD = timedelta(days=3)

UNKNOWN_ADMISSION_REASON = "unknown"


class WarmingAdmissionReason(StrEnum):
    """Which branch of `insights_to_keep_fresh` let this insight into the warm set."""

    DASHBOARD = "dashboard"
    SINGLE = "single"
    SHARED_DASHBOARD = "shared_dashboard"
    SHARED_SINGLE = "shared_single"


class InsightViewAge(StrEnum):
    """Bucketed days since anyone last opened the insight itself.

    A dashboard-admitted insight can sit in any bucket: opening a dashboard does not record a
    view against each of its tiles, so `DASHBOARD` warming and `NEVER` is the expected pairing
    for a tile nobody clicks into.
    """

    NEVER = "never"
    D0_1 = "0-1"
    D1_3 = "1-3"
    D3_7 = "3-7"
    D7_14 = "7-14"
    D14_30 = "14-30"
    D30_PLUS = "30+"


_VIEW_AGE_BUCKETS: tuple[tuple[int, InsightViewAge], ...] = (
    (1, InsightViewAge.D0_1),
    (3, InsightViewAge.D1_3),
    (7, InsightViewAge.D3_7),
    (14, InsightViewAge.D7_14),
    (30, InsightViewAge.D14_30),
)


def view_age_bucket(last_viewed_at: Optional[datetime], *, now: datetime) -> InsightViewAge:
    if last_viewed_at is None:
        return InsightViewAge.NEVER
    days = (now - last_viewed_at).total_seconds() / 86400
    for upper_bound, bucket in _VIEW_AGE_BUCKETS:
        if days < upper_bound:
            return bucket
    return InsightViewAge.D30_PLUS


@frozen
class WarmingCandidate:
    """One insight (optionally as tiled on one dashboard) admitted to a warming pass, with the
    selection context that admitted it."""

    insight_id: int
    dashboard_id: Optional[int]
    admission_reason: WarmingAdmissionReason
    insight_view_age: InsightViewAge


# ClickHouse capacity/concurrency errors that should retry with backoff rather than fail the task.
# ClickHouseAtCapacity is included via CH_TRANSIENT_ERRORS (it's what codes 202/439 surface as).
RETRIABLE_WARMING_ERRORS = (*CH_TRANSIENT_ERRORS, ConcurrencyLimitExceeded)


def teams_enabled_for_cache_warming() -> list[int]:
    enabled_team_ids = []

    for team_id, organization_id, uuid in Team.objects.values_list(
        "id",
        "organization_id",
        "uuid",
    ).iterator(chunk_size=1000):
        enabled = posthoganalytics.feature_enabled(
            "cache-warming",
            str(uuid),
            groups={
                "organization": str(organization_id),
                "project": str(team_id),
            },
            group_properties={
                "organization": {
                    "id": str(organization_id),
                },
                "project": {
                    "id": str(team_id),
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

        if enabled:
            enabled_team_ids.append(team_id)

    return enabled_team_ids


def insights_to_keep_fresh(team: Team, shared_only: bool = False) -> Generator[WarmingCandidate]:
    """
    This is the place to decide which insights should be kept warm for the provided team.
    The reasoning is that this will be a yes or no decision. If we need to keep it warm, we try our best
    to not let the cache go stale. There isn't any middle ground, like trying to refresh it once a day, since
    that would be like clock that's only right twice a day.
    """
    now = datetime.now(UTC)
    # for shared insights, use a lower cut off
    threshold = now - (LAST_VIEWED_THRESHOLD if not shared_only else SHARED_INSIGHTS_LAST_VIEWED_THRESHOLD)

    clean_up_stale_insights(team_id=team.pk, threshold=threshold)

    # get all insights currently in the cache for the team
    combos = get_stale_insights(team_id=team.pk, limit=500)

    STALE_INSIGHTS_GAUGE.labels(team_id=team.pk).set(len(combos))

    dashboard_q_filter = Q()
    insight_ids_single = set()

    for insight_id, dashboard_id in (combo.split(":") for combo in combos):
        if dashboard_id:
            dashboard_q_filter |= Q(insight_id=insight_id, dashboard_id=dashboard_id)
        else:
            insight_ids_single.add(insight_id)

    if insight_ids_single:
        single_insight_q_filter = Q(
            team=team,
            insightviewed__last_viewed_at__gte=threshold,
            pk__in=insight_ids_single,
        )
        if shared_only:
            single_insight_q_filter &= Q(sharingconfiguration__enabled=True)

        single_insights = (
            with_last_viewed_at(Insight.objects.filter(single_insight_q_filter))
            .distinct()
            .values_list("id", "last_viewed_at")
        )
        for single_insight_id, last_viewed_at in single_insights:
            yield WarmingCandidate(
                insight_id=single_insight_id,
                dashboard_id=None,
                admission_reason=WarmingAdmissionReason.SHARED_SINGLE if shared_only else WarmingAdmissionReason.SINGLE,
                insight_view_age=view_age_bucket(last_viewed_at, now=now),
            )

    if not dashboard_q_filter:
        return

    if shared_only:
        dashboard_q_filter &= Q(dashboard__sharingconfiguration__enabled=True)

    dashboard_tiles = list(
        DashboardTile.objects.filter(dashboard__last_accessed_at__gte=threshold)
        .filter(dashboard_q_filter)
        .distinct()
        .values_list("insight_id", "dashboard_id")
    )
    if not dashboard_tiles:
        return

    # The tile's own view recency, which the dashboard filter above never consults. This is the
    # value that made "warmed but never viewed" a cross-store join to answer.
    last_viewed_at_by_insight_id = dict(
        with_last_viewed_at(
            Insight.objects.filter(team=team, pk__in={insight_id for insight_id, _ in dashboard_tiles})
        ).values_list("id", "last_viewed_at")
    )

    for insight_id, dashboard_id in dashboard_tiles:
        yield WarmingCandidate(
            insight_id=insight_id,
            dashboard_id=dashboard_id,
            admission_reason=WarmingAdmissionReason.SHARED_DASHBOARD
            if shared_only
            else WarmingAdmissionReason.DASHBOARD,
            insight_view_age=view_age_bucket(last_viewed_at_by_insight_id.get(insight_id), now=now),
        )


@shared_task(ignore_result=True, expires=60 * 15)
@skip_team_scope_audit
def schedule_warming_for_teams_task():
    """
    Runs every hour and schedule warming for all insights (picked from insights_to_cache)
    for each team enabled for cache warming.

    We trigger recalculation using ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
    so even though we might pick all insights for a team to recalculate,
    only the stale ones (determined by `staleness_threshold_map`) get recalculated.
    """
    from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level

    kill_switch_level = get_kill_switch_level()
    if kill_switch_level != KillSwitchLevel.OFF:
        logger.info("kill_switch_on_skipping_cache_warming", level=kill_switch_level)
        return

    team_ids = largest_teams(limit=10)
    threshold = datetime.now(UTC) - LAST_VIEWED_THRESHOLD

    enabled_teams = Team.objects.filter(
        Q(pk__in=team_ids)
        | Q(extra_settings__insights_cache_warming=True)
        | Q(pk__in=teams_enabled_for_cache_warming())
    )
    teams_with_recently_viewed_shared = Team.objects.filter(
        Q(
            Q(sharingconfiguration__dashboard__last_accessed_at__gte=threshold)
            | Q(sharingconfiguration__insight__insightviewed__last_viewed_at__gte=threshold)
        ),
        sharingconfiguration__enabled=True,
    ).difference(enabled_teams)

    all_teams = itertools.chain(
        zip(enabled_teams, [False] * len(enabled_teams)),
        zip(teams_with_recently_viewed_shared, [True] * len(teams_with_recently_viewed_shared)),
    )

    # Use a fixed expiration time since tasks in the chain are executed sequentially
    expire_after = datetime.now(UTC) + timedelta(minutes=50)

    with ph_scoped_capture() as capture_ph_event:
        for team, shared_only in all_teams:
            candidates = list(insights_to_keep_fresh(team, shared_only=shared_only))

            capture_ph_event(
                distinct_id=str(team.uuid),
                event="cache warming - insights to cache",
                properties={
                    "count": len(candidates),
                    "team_id": team.id,
                    "organization_id": team.organization_id,
                    "shared_only": shared_only,
                },
            )

            # We chain the task execution to prevent queries *for a single team* running at the same time
            chain(
                *(
                    warm_insight_cache_task.si(
                        candidate.insight_id,
                        candidate.dashboard_id,
                        admission_reason=candidate.admission_reason.value,
                        insight_view_age=candidate.insight_view_age.value,
                    ).set(expires=expire_after)
                    for candidate in candidates
                )
            )()


@shared_task(
    queue=CeleryQueue.ANALYTICS_LIMITED.value,  # Important! Prevents Clickhouse from being overwhelmed
    ignore_result=True,
    expires=60 * 60,
    autoretry_for=RETRIABLE_WARMING_ERRORS,
    retry_backoff=2,
    retry_backoff_max=3,
    max_retries=3,
)
def warm_insight_cache_task(
    insight_id: int,
    dashboard_id: Optional[int],
    admission_reason: Optional[str] = None,
    insight_view_age: Optional[str] = None,
):
    try:
        # nosemgrep: idor-lookup-without-team (Celery task, ID from internal scheduling)
        insight = Insight.objects.select_related("team__organization").get(pk=insight_id)
    except Insight.DoesNotExist:
        logger.info(f"Warming insight cache failed 404 insight not found: {insight_id}")
        return

    if insight.query is None:
        logger.info(f"Warming insight cache skipped, insight has no query: {insight_id}")
        return

    dashboard = None

    tag_queries(
        **get_team_query_tags(insight.team),
        insight_id=insight.pk,
        trigger="warmingV2",
        feature=Feature.CACHE_WARMUP,
        warming_admission_reason=admission_reason,
        warming_insight_view_age=insight_view_age,
    )
    if dashboard_id:
        tag_queries(dashboard_id=dashboard_id)
        dashboard = insight.dashboards.filter(pk=dashboard_id).first()

    with upgrade_insight(insight):
        logger.info(f"Warming insight cache: {insight.pk} for team {insight.team_id} and dashboard {dashboard_id}")

        try:
            tile = dashboard.tiles.filter(insight=insight).first() if dashboard is not None else None
            variables_override = (
                variables_override_requested_by_client(None, dashboard, insight_variables_for_team(insight.team_id))
                if dashboard is not None and dashboard.variables
                else None
            )
            # The same call a dashboard load makes, so warming writes the cache key the page reads.
            results = calculate_for_query_based_insight(
                insight,
                team=insight.team,
                dashboard=dashboard,
                # We need an execution mode with recent cache:
                # - in case someone refreshed after this task was triggered
                # - if insight + dashboard combinations have the same cache key, we prevent needless recalculations
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=insight.created_by,
                variables_override=variables_override,
                tile_filters_override=tile.filters_overrides if tile is not None else None,
                analytics_props={"source": EventSource.CACHE_WARMING},
            )

            is_cached = results.is_cached

            PRIORITY_INSIGHTS_COUNTER.labels(
                team_id=insight.team_id,
                dashboard=dashboard_id is not None,
                is_cached=is_cached,
                admission_reason=admission_reason or UNKNOWN_ADMISSION_REASON,
            ).inc()

            with ph_scoped_capture() as capture_ph_event:
                capture_ph_event(
                    distinct_id=str(insight.team.uuid),
                    event="cache warming - warming insight",
                    properties={
                        "insight_id": insight.pk,
                        "insight_short_id": insight.short_id,
                        "dashboard_id": dashboard_id,
                        "is_cached": is_cached,
                        "team_id": insight.team_id,
                        "organization_id": insight.team.organization_id,
                    },
                )

        except RETRIABLE_WARMING_ERRORS:
            raise
        except Exception as e:
            # A revoked creator's access-denied error is a known limitation - report it as an event
            # rather than surfacing it in error tracking.
            if isinstance(e, TableAccessDeniedError) and creator_access_revoked(insight.created_by, insight.team):
                report_creator_access_revoked(
                    user=insight.created_by,
                    team=insight.team,
                    source="cache_warming",
                    error=e,
                    properties={"insight_id": insight.pk, "dashboard_id": dashboard_id},
                )
            elif isinstance(e, ExposedHogQLError):
                # The query itself is wrong, and only its author can correct it. Report it as an
                # event so it stays with the team instead of becoming an issue in our error tracking.
                with ph_scoped_capture() as capture_ph_event:
                    capture_ph_event(
                        distinct_id=str(insight.team.uuid),
                        event="cache warming - insight query error",
                        properties={
                            "insight_id": insight.pk,
                            "insight_short_id": insight.short_id,
                            "dashboard_id": dashboard_id,
                            "team_id": insight.team_id,
                            "organization_id": str(insight.team.organization_id),
                            "error_code": e.code_name,
                            "error": str(e),
                        },
                    )
            else:
                capture_exception(e)

"""Explicit manual API; no production query path enables this automatically.

Historical TTL is a staleness contract, not proof of immutability. The caller must
own refresh scheduling and bump revision on relevant source/identity invalidation.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select

from posthog.models.team import Team

from products.analytics_platform.backend.lazy_computation.hourly_uniq import HourlyUniqPlan
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    TtlSchedule,
    ensure_precomputed,
)


@dataclass(frozen=True)
class HourlyUniqFreshness:
    historical_ttl_seconds: int
    live_hours: int
    revision: str

    refresh_bands: tuple[tuple[int, int], ...] = ()
    historical_jitter_seconds: int = 0

    def __post_init__(self) -> None:
        if (
            not 0 < self.historical_ttl_seconds <= 7 * 86400
            or not 0 <= self.live_hours <= 24 * 30
            or not self.revision
            or not 0 <= self.historical_jitter_seconds <= 86400
        ):
            raise ValueError("Invalid historical TTL, live hours, jitter, or invalidation revision")
        previous_age = 0
        previous_ttl = 0
        for age_hours, ttl in self.refresh_bands:
            if age_hours <= previous_age or not previous_ttl < ttl <= self.historical_ttl_seconds:
                raise ValueError("Refresh bands must have increasing positive ages and TTLs")
            previous_age, previous_ttl = age_hours, ttl

    @classmethod
    def age_based(cls, *, revision: str) -> "HourlyUniqFreshness":
        """Experimental opt-in policy, not a production alert freshness guarantee."""
        return cls(
            historical_ttl_seconds=7 * 86400,
            live_hours=0,
            revision=revision,
            refresh_bands=((48, 3600), (96, 18 * 3600)),
            historical_jitter_seconds=6 * 3600,
        )

    def schedule(self, end: datetime) -> TtlSchedule:
        # Shared coverage is UTC-day based. Align the policy to those same jobs;
        # the current partial day stays live, even when live_hours is zero.
        day = end.replace(hour=0, minute=0, second=0, microsecond=0)
        return TtlSchedule(
            rules=[(day - timedelta(hours=age), ttl) for age, ttl in self.refresh_bands],
            default_ttl_seconds=self.historical_ttl_seconds,
            max_window_days=1,
            default_ttl_jitter_seconds=self.historical_jitter_seconds or None,
        )


def _coverage(
    team: Team,
    plan: HourlyUniqPlan,
    policy: HourlyUniqFreshness,
    modifiers: HogQLQueryModifiers | None,
    *,
    warm: bool,
    budget: float,
) -> tuple[LazyComputationResult | None, datetime]:
    if team.timezone != plan.timezone:
        raise ValueError("The plan timezone must match the executing team")
    start = plan.start.replace(hour=0, minute=0, second=0, microsecond=0)
    cut = (plan.end - timedelta(hours=policy.live_hours)).replace(hour=0, minute=0, second=0, microsecond=0)
    if cut <= plan.start:
        return None, cut
    effective = create_default_modifiers_for_team(team, modifiers)
    result = ensure_precomputed(
        team=team,
        insert_query=plan.insert_query,
        time_range_start=start,
        time_range_end=cut,
        ttl_seconds=policy.schedule(plan.end),
        table=LazyComputationTable.HOURLY_UNIQ_PREAGGREGATED,
        query_type="hourly_uniq_precompute",
        modifiers=effective,
        cache_key_context={
            "version": "hourly-uniq-v1",
            "revision": policy.revision,
            "modifiers": json.dumps(effective.model_dump(mode="json"), sort_keys=True),
        },
        run_inserts=warm,
        wait_timeout_seconds=budget,
        end_is_data_horizon=True,
    )
    return result, cut


def warm_hourly_uniq(
    team: Team,
    plan: HourlyUniqPlan,
    policy: HourlyUniqFreshness,
    *,
    modifiers: HogQLQueryModifiers | None = None,
    budget_seconds: float = 30,
) -> LazyComputationResult | None:
    """Explicit bounded build. Schedule separately from reads with caller-owned concurrency."""
    if not 0 < budget_seconds <= 300:
        raise ValueError("Warm-up budget must be between 0 and 300 seconds")
    return _coverage(team, plan, policy, modifiers, warm=True, budget=budget_seconds)[0]


def read_hourly_uniq(
    team: Team, plan: HourlyUniqPlan, policy: HourlyUniqFreshness, *, modifiers: HogQLQueryModifiers | None = None
) -> ast.SelectQuery | None:
    """Return a query only with complete fresh coverage; never build or wait on a miss.

    Execute the returned AST with the SAME modifiers and caller permissions. This
    returns the complete series; the consumer must not apply dashboard pagination.
    """
    coverage, cut = _coverage(team, plan, policy, modifiers, warm=False, budget=30)
    if coverage is None or not coverage.ready or coverage.errors or coverage.stale or not coverage.job_ids:
        return None
    cached = parse_select(
        "SELECT time_window_start, metric_index, uniq_state FROM hourly_uniq_preaggregated WHERE job_id IN {jobs} AND time_window_start >= {start} AND time_window_start < {cut}",
        placeholders={
            "jobs": ast.Tuple(exprs=[ast.Constant(value=str(j)) for j in coverage.job_ids]),
            "start": ast.Constant(value=plan.start),
            "cut": ast.Constant(value=cut),
        },
    )
    live = plan.states(ast.Constant(value=cut), ast.Constant(value=plan.end))
    union = ast.SelectSetQuery(
        initial_select_query=cached,
        subsequent_select_queries=[ast.SelectSetNode(select_query=live, set_operator="UNION ALL")],
    )
    return plan.combine(union)

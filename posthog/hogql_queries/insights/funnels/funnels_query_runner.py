import threading
from collections.abc import Sequence
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Optional

from django.conf import settings

import structlog
import posthoganalytics

from posthog.schema import (
    CachedFunnelsQueryResponse,
    DateRange,
    FunnelsQuery,
    FunnelsQueryResponse,
    FunnelVizType,
    HogQLQueryModifiers,
    ResolvedDateRangeResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY, HogQLGlobalSettings, LimitContext
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.clickhouse import query_tagging
from posthog.clickhouse.query_tagging import QueryTags
from posthog.hogql_queries.insights.funnels import FunnelTrendsUDF, FunnelUDF
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.funnel_time_to_convert import FunnelTimeToConvertUDF
from posthog.hogql_queries.insights.funnels.funnel_validation_rules import (
    RequireAtLeastTwoFunnelSteps,
    ValidateFunnelExclusions,
    ValidateFunnelStepRange,
    ValidateOptionalFunnelSteps,
)
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.hogql_queries.validation.rules import DisallowUnsupportedDataWarehouseSettings
from posthog.hogql_queries.validation.validation import QueryValidationRule
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property

logger = structlog.get_logger(__name__)


class FunnelsQueryRunner(AnalyticsQueryRunner[FunnelsQueryResponse]):
    query: FunnelsQuery
    cached_response: CachedFunnelsQueryResponse
    context: FunnelQueryContext

    def __init__(
        self,
        query: FunnelsQuery | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        just_summarize: bool = False,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

        self.just_summarize = just_summarize
        self.context = FunnelQueryContext(
            query=self.query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context
        )

    def validators(self) -> Sequence[QueryValidationRule[FunnelsQuery]]:
        return (
            RequireAtLeastTwoFunnelSteps(),
            ValidateFunnelStepRange(),
            ValidateFunnelExclusions(),
            ValidateOptionalFunnelSteps(),
            DisallowUnsupportedDataWarehouseSettings(),
        )

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return refresh_frequency

    def to_query(self) -> ast.SelectQuery:
        return self.funnel_class.get_query()

    def to_actors_query(self) -> ast.SelectQuery:
        return self.funnel_actor_class.actor_query()

    def _calculate(self):
        if self._is_compare_active():
            return self._calculate_compare()
        return self._calculate_single_period(self.funnel_class)

    def _calculate_single_period(
        self, funnel_class, timings_override: Optional[HogQLTimings] = None
    ) -> FunnelsQueryResponse:
        query = funnel_class.get_query()
        # Compare runs subqueries in parallel threads; each worker passes its own clone since
        # HogQLTimings is not thread-safe. Single-period runs fall back to the shared instance.
        effective_timings = timings_override if timings_override is not None else self.timings
        timings = []

        # TODO: can we get this from execute_hogql_query as well?
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="FunnelsQuery",
            query=query,
            team=self.team,
            timings=effective_timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            settings=HogQLGlobalSettings(
                # Make sure funnel queries never OOM
                max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
            ),
        )

        results = funnel_class._format_results(response.results)

        if response.timings is not None:
            timings.extend(response.timings)

        return FunnelsQueryResponse(
            results=results,
            timings=timings,
            hogql=hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )

    def _calculate_compare(self) -> FunnelsQueryResponse:
        """Run current + previous period queries and merge tagged rows.

        Each row in `results: Any` is tagged with `compare_label: 'current' | 'previous'`. The
        response shape is otherwise identical to a single-period response — this is the contract
        the frontend (and later viz-mode slices) rely on. Two parallel queries instead of a UNION
        because funnel queries are CTE/UDF-heavy; doubling cost is the explicit trade-off.
        """
        previous_funnel = self._build_previous_funnel()
        responses: list[Optional[FunnelsQueryResponse]] = [None, None]
        errors: list[Exception] = []
        funnels = [self.funnel_class, previous_funnel]

        def run(index: int, timings: HogQLTimings, query_tags: Optional[QueryTags] = None) -> None:
            try:
                # Worker threads start with an empty QueryTags ContextVar — restore the parent's
                # snapshot so execute_hogql_query has the required feature/product tags.
                if query_tags is not None:
                    query_tagging.update_tags(query_tags)
                responses[index] = self._calculate_single_period(funnels[index], timings_override=timings)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                if not settings.IN_UNIT_TESTING:
                    # Close the per-thread DB connection so this thread doesn't leak it.
                    from django.db import connection

                    connection.close()

        if settings.IN_UNIT_TESTING:
            # Django + threads in tests is flaky; trends compare uses the same bypass.
            for index in range(len(funnels)):
                run(index, self.timings.clone_for_subquery(index))
        else:
            parent_tags = query_tagging.get_query_tags().model_copy(deep=True)
            jobs = [
                threading.Thread(
                    target=run,
                    args=(index, self.timings.clone_for_subquery(index), parent_tags),
                )
                for index in range(len(funnels))
            ]
            for job in jobs:
                job.start()
            for job in jobs:
                job.join()

        if errors:
            # Surface every secondary error with its traceback before re-raising the first,
            # so dual-query failures don't disappear into the void.
            for dropped in errors[1:]:
                logger.exception("funnels_compare_secondary_error", exc_info=dropped)
            raise errors[0]

        current_response, previous_response = responses
        assert current_response is not None and previous_response is not None

        merged_results = []
        for row in current_response.results or []:
            row["compare_label"] = "current"
            merged_results.append(row)
        for row in previous_response.results or []:
            row["compare_label"] = "previous"
            merged_results.append(row)

        timings = list(current_response.timings or []) + list(previous_response.timings or [])

        return FunnelsQueryResponse(
            results=merged_results,
            timings=timings,
            hogql=current_response.hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )

    def _build_previous_funnel(self) -> FunnelTrendsUDF:
        """Construct a FunnelTrendsUDF pinned to the previous-period date range.

        The previous query is a clone of `self.query` with its `dateRange` swapped for the
        shifted range and `compareFilter` cleared (to prevent infinite recursion if the cloned
        query ever flows back through this runner).
        """
        prev_date_from = self.query_previous_date_range.date_from()
        prev_date_to = self.query_previous_date_range.date_to()
        previous_query = self.query.model_copy(
            update={
                "dateRange": DateRange(
                    date_from=prev_date_from.isoformat() if prev_date_from else None,
                    date_to=prev_date_to.isoformat() if prev_date_to else None,
                    explicitDate=True,
                ),
                "compareFilter": None,
            }
        )
        previous_context = FunnelQueryContext(
            query=previous_query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        return FunnelTrendsUDF(context=previous_context, just_summarize=self.just_summarize)

    def _is_compare_active(self) -> bool:
        compare_filter = self.query.compareFilter
        if compare_filter is None or not compare_filter.compare:
            return False
        # Slice 1 ships compare only for the TRENDS viz mode. Other viz modes land in later slices.
        if self.context.funnelsFilter.funnelVizType != FunnelVizType.TRENDS:
            return False
        return self._team_flag_funnels_compare()

    def _team_flag_funnels_compare(self) -> bool:
        return posthoganalytics.feature_enabled(
            "funnels-compare",
            str(self.team.uuid),
            groups={
                "organization": str(self.team.organization_id),
                "project": str(self.team.id),
            },
            group_properties={
                "organization": {"id": str(self.team.organization_id)},
                "project": {"id": str(self.team.id)},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    @cached_property
    def funnel_order_class(self):
        return FunnelUDF(context=self.context)

    @cached_property
    def funnel_class(self):
        funnelVizType = self.context.funnelsFilter.funnelVizType

        if funnelVizType == FunnelVizType.TRENDS:
            return FunnelTrendsUDF(context=self.context, just_summarize=self.just_summarize)
        elif funnelVizType == FunnelVizType.TIME_TO_CONVERT:
            return FunnelTimeToConvertUDF(context=self.context)
        else:
            return self.funnel_order_class

    @cached_property
    def funnel_actor_class(self):
        if self.context.funnelsFilter.funnelVizType == FunnelVizType.TRENDS:
            return FunnelTrendsUDF(context=self.context)

        return FunnelUDF(context=self.context)

    @property
    def exact_timerange(self):
        return self.query.dateRange and self.query.dateRange.explicitDate

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
            exact_timerange=self.exact_timerange,
        )

    @cached_property
    def query_previous_date_range(self) -> QueryDateRange:
        compare_filter = self.query.compareFilter
        if compare_filter is not None and compare_filter.compare_to:
            return QueryCompareToDateRange(
                date_range=self.query.dateRange,
                team=self.team,
                interval=self.query.interval,
                now=datetime.now(),
                compare_to=compare_filter.compare_to,
            )
        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
        )

import json
import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Optional, TypeVar, cast

from django.conf import settings

import structlog

from posthog.schema import (
    BreakdownFilter,
    BreakdownItem,
    CachedFunnelsQueryResponse,
    Compare,
    CompareItem,
    DateRange,
    FunnelsQuery,
    FunnelsQueryResponse,
    FunnelTimeToConvertResults,
    FunnelVizType,
    HogQLQueryModifiers,
    InsightActorsQueryOptionsResponse,
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
from posthog.hogql_queries.insights.funnels.funnel_time_to_convert_bins import (
    ConversionTimeRange,
    compute_shared_bin_boundaries,
)
from posthog.hogql_queries.insights.funnels.funnel_validation_rules import (
    RequireAtLeastTwoFunnelSteps,
    ValidateFunnelExclusions,
    ValidateFunnelStepRange,
    ValidateOptionalFunnelSteps,
)
from posthog.hogql_queries.insights.utils.breakdowns import (
    ALL_USERS_COHORT_ID,
    BREAKDOWN_BASELINE_DISPLAY,
    BREAKDOWN_BASELINE_STRING_LABEL,
    BREAKDOWN_NULL_DISPLAY,
    has_breakdown_filter,
    humanize_breakdown_label,
)
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.hogql_queries.validation.rules import DisallowUnsupportedDataWarehouseSettings
from posthog.hogql_queries.validation.validation import QueryValidationRule
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.queries.breakdown_props import get_breakdown_cohort_name

from products.cohorts.backend.models.cohort import Cohort

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")


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
        user: Optional[User] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context, user=user)

        self.just_summarize = just_summarize
        self.context = FunnelQueryContext(
            query=self.query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
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
        # A persons modal opened from a 'previous' compare bar must return actors from the shifted
        # window only; every other case uses the source's own (current) date range.
        actors_query = self.context.actorsQuery
        if actors_query is not None and actors_query.compare == Compare.PREVIOUS:
            previous_context = self._previous_period_context()
            previous_context.actorsQuery = actors_query
            return self._actor_class_for_context(previous_context).actor_query()
        return self.funnel_actor_class.actor_query()

    def to_actors_query_options(self) -> InsightActorsQueryOptionsResponse:
        res_compare: Optional[list[CompareItem]] = None
        res_breakdown: Optional[list[BreakdownItem]] = None

        # No period switch for the TRENDS viz: its actors are pinned to an absolute
        # funnelTrendsEntrancePeriodStart, which exists in only one period's date range,
        # so switching would always return an empty list.
        if self._is_compare_active() and self.context.funnelsFilter.funnelVizType != FunnelVizType.TRENDS:
            res_compare = [
                CompareItem(label="Current", value="current"),
                CompareItem(label="Previous", value="previous"),
            ]

        breakdown_filter = self.query.breakdownFilter
        if has_breakdown_filter(breakdown_filter):
            assert breakdown_filter is not None  # type checking
            # Baseline = no breakdown filter (funnelStepBreakdown: null), mirroring the synthetic
            # "Baseline" row the funnel steps table renders.
            items: list[BreakdownItem] = [
                BreakdownItem(label=BREAKDOWN_BASELINE_DISPLAY, value=BREAKDOWN_BASELINE_STRING_LABEL)
            ]
            if breakdown_filter.breakdown_type == "cohort":
                items += self._cohort_breakdown_options(breakdown_filter)
            else:
                items += self._result_breakdown_options()
            if len(items) > 1:  # Baseline alone means there are no values to switch between
                res_breakdown = items

        return InsightActorsQueryOptionsResponse(compare=res_compare, breakdown=res_breakdown)

    def _cohort_breakdown_options(self, breakdown_filter: BreakdownFilter) -> list[BreakdownItem]:
        # Cohort options come from the filter itself: the raw ids are what the actor query's
        # breakdown condition matches (TRENDS-viz results only carry display names).
        breakdown = breakdown_filter.breakdown
        values = breakdown if isinstance(breakdown, list) else [breakdown]
        items: list[BreakdownItem] = []
        for value in values:
            if value == "all" or str(value) == str(ALL_USERS_COHORT_ID):
                items.append(BreakdownItem(label="all users", value=ALL_USERS_COHORT_ID))
                continue
            try:
                cohort_id = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            try:
                label = get_breakdown_cohort_name(cohort_id, self.team)
            except Cohort.DoesNotExist:
                label = str(cohort_id)
            items.append(BreakdownItem(label=label, value=cohort_id))
        return items

    def _result_breakdown_options(self) -> list[BreakdownItem]:
        items: list[BreakdownItem] = []
        seen: set[tuple] = set()
        for value in self._result_breakdown_values():
            # Compare-merged results carry each breakdown value once per period; dedupe
            # while preserving result order (current period first).
            key = tuple(value) if isinstance(value, list) else (value,)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                BreakdownItem(label=self._breakdown_option_label(value), value=self._breakdown_option_value(value))
            )
        return items

    def _result_breakdown_values(self) -> list[Any]:
        results = self._own_results()
        if self.context.funnelsFilter.funnelVizType == FunnelVizType.TRENDS:
            return [row["breakdown_value"] for row in results if isinstance(row, dict) and "breakdown_value" in row]
        if self._is_breakdown_groups(results):
            return [
                group[0]["breakdown_value"]
                for group in results
                if group and isinstance(group[0], dict) and "breakdown_value" in group[0]
            ]
        return []

    def _own_results(self) -> list:
        # The persons modal opens from a rendered funnel, so the insight cache is normally hot;
        # recalculate only on a miss (matching the trends options builder's cost profile, which
        # always executes a query).
        cached = self.run(ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)
        if isinstance(cached, CachedFunnelsQueryResponse) and cached.results:
            return cached.results
        return self.calculate().results or []

    @staticmethod
    def _breakdown_option_value(value: Any) -> str | int:
        if isinstance(value, list):
            if len(value) == 1:
                # Safe to unwrap: the actor query compares via arrayFlatten(array(...)) on both
                # sides, which normalizes scalar vs single-element array.
                value = value[0]
            else:
                # Multi-property values must fit BreakdownItem's str|int schema; the modal parses
                # this back into an array for funnelStepBreakdown.
                return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, int):
            return value
        return str(value)

    @staticmethod
    def _breakdown_option_label(value: Any) -> str:
        parts = value if isinstance(value, list) else [value]
        labels = [
            # Funnels encode a missing property value as '' (unlike trends' null sentinel).
            BREAKDOWN_NULL_DISPLAY if part is None or str(part) == "" else humanize_breakdown_label(str(part))
            for part in parts
        ]
        return ", ".join(labels)

    def _calculate(self):
        if self._is_compare_active():
            return self._calculate_compare()
        return self._calculate_single_period(self.funnel_class)

    def _calculate_single_period(
        self,
        funnel_class,
        timings_override: Optional[HogQLTimings] = None,
        date_range_override: Optional[QueryDateRange] = None,
    ) -> FunnelsQueryResponse:
        query = funnel_class.get_query()
        # Compare runs subqueries in parallel threads; each worker passes its own clone since
        # HogQLTimings is not thread-safe. Single-period runs fall back to the shared instance.
        effective_timings = timings_override if timings_override is not None else self.timings
        # Previous-period funnels resolve a shifted date range; without the override the response
        # would advertise the current-period range, which is wrong for any caller that inspects
        # resolved_date_range on a non-current sub-response.
        effective_date_range = date_range_override if date_range_override is not None else self.query_date_range
        timings = []

        # TODO: can we get this from execute_hogql_query as well?
        # Display-only response HogQL (never executed); bypass warehouse ACL so printing doesn't fail closed userless.
        hogql = to_printed_hogql(query, self.team, bypass_warehouse_access_control=True)

        response = execute_hogql_query(
            query_type="FunnelsQuery",
            query=query,
            team=self.team,
            user=self.user,
            timings=effective_timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            settings=HogQLGlobalSettings(
                # Make sure funnel queries never OOM
                max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
            ),
        )

        results = funnel_class._format_results(response.results)
        total_median_conversion_time = funnel_class._extract_total_median_conversion_time(
            response.results, response.columns
        )

        if response.timings is not None:
            timings.extend(response.timings)

        return FunnelsQueryResponse(
            results=results,
            total_median_conversion_time=total_median_conversion_time,
            timings=timings,
            hogql=hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=effective_date_range.date_from(),
                date_to=effective_date_range.date_to(),
            ),
        )

    def _run_in_parallel(self, tasks: list[Callable[[HogQLTimings], "_T"]], index_offset: int = 0) -> list["_T"]:
        """Run sub-query callables concurrently and return their results in order.

        Each task receives its own cloned `HogQLTimings` (not thread-safe to share). In unit tests
        we run serially because Django + threads is flaky there — trends compare uses the same bypass.
        """
        results: list[Optional[_T]] = [None] * len(tasks)
        errors: list[Exception] = []

        def run(index: int, timings: HogQLTimings, query_tags: Optional[QueryTags] = None) -> None:
            try:
                # Worker threads start with an empty QueryTags ContextVar — restore the parent's
                # snapshot so execute_hogql_query has the required feature/product tags.
                if query_tags is not None:
                    query_tagging.update_tags(query_tags)
                results[index] = tasks[index](timings)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                if not settings.IN_UNIT_TESTING:
                    # Close the per-thread DB connection so this thread doesn't leak it.
                    from django.db import connection

                    connection.close()

        if settings.IN_UNIT_TESTING:
            for index in range(len(tasks)):
                run(index, self.timings.clone_for_subquery(index_offset + index))
        else:
            parent_tags = query_tagging.get_query_tags().model_copy(deep=True)
            jobs = [
                threading.Thread(
                    target=run,
                    args=(index, self.timings.clone_for_subquery(index_offset + index), parent_tags),
                )
                for index in range(len(tasks))
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

        return cast(list["_T"], results)

    def _calculate_compare(self) -> FunnelsQueryResponse:
        if self.context.funnelsFilter.funnelVizType == FunnelVizType.TIME_TO_CONVERT:
            return self._calculate_compare_time_to_convert()
        return self._calculate_compare_tagged_rows()

    def _calculate_compare_tagged_rows(self) -> FunnelsQueryResponse:
        """Run current + previous period queries and merge tagged rows.

        Each row in `results: Any` is tagged with `compare_label: 'current' | 'previous'`. The
        response shape is otherwise identical to a single-period response — this is the contract
        the frontend (and later viz-mode slices) rely on. Two parallel queries instead of a UNION
        because funnel queries are CTE/UDF-heavy; doubling cost is the explicit trade-off.
        """
        previous_funnel = self._build_previous_funnel()

        # Each lambda passes its own period's date range through `date_range_override` so the
        # sub-response's resolved_date_range matches the period it computed, instead of leaking
        # the current-period range into the previous-period response.
        current_response, previous_response = self._run_in_parallel(
            [
                lambda timings: self._calculate_single_period(
                    self.funnel_class,
                    timings_override=timings,
                    date_range_override=self.query_date_range,
                ),
                lambda timings: self._calculate_single_period(
                    previous_funnel,
                    timings_override=timings,
                    date_range_override=self.query_previous_date_range,
                ),
            ]
        )

        current_results = current_response.results or []
        previous_results = previous_response.results or []

        is_steps = self.context.funnelsFilter.funnelVizType == FunnelVizType.STEPS

        if is_steps and self._is_breakdown_groups(current_results or previous_results):
            # Breakdown STEPS return one inner funnel (a list of step dicts) per breakdown value.
            # Compare doubles this to 2·N inner funnels — N current + N previous — tagging each
            # step and aligning the periods by breakdown value (TRENDS keeps its flat dict rows).
            merged_results = self._merge_breakdown_compare_groups(current_results, previous_results)
        else:
            # Flat STEPS returns an empty list for a period with no matching events. Backfill it
            # with a zeroed step skeleton (cloned from the populated period) so the grouped-bar
            # chart still draws a bar per step on both sides instead of collapsing to a single bar.
            # TRENDS and TIME_TO_CONVERT always return a populated skeleton, so this only fires for
            # flat STEPS.
            if is_steps and current_results and not previous_results:
                previous_results = self._zeroed_steps_skeleton(current_results)
            elif is_steps and previous_results and not current_results:
                current_results = self._zeroed_steps_skeleton(previous_results)

            merged_results = []
            for row in current_results:
                row["compare_label"] = "current"
                merged_results.append(row)
            for row in previous_results:
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

    def _zeroed_steps_skeleton(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Clone a flat list of step dicts with all counts and conversion times zeroed.

        Used for the empty side of a STEPS compare so it mirrors the populated period's step
        names/orders/types while reporting zero conversions.
        """
        return [
            {
                **step,
                "count": 0,
                "people": [],
                "average_conversion_time": None,
                "median_conversion_time": None,
            }
            for step in steps
        ]

    @staticmethod
    def _is_breakdown_groups(results: list) -> bool:
        """Whether a results payload is breakdown STEPS — a list of inner funnels (one list of step
        dicts per breakdown value) rather than a flat list of step dicts."""
        return bool(results) and all(isinstance(row, list) for row in results)

    @staticmethod
    def _breakdown_key(group: list[dict[str, Any]]) -> tuple:
        """Hashable identity for an inner funnel — its breakdown_value (a list) as a tuple."""
        value = group[0].get("breakdown_value") if group else None
        return tuple(value) if isinstance(value, list) else (value,)

    def _merge_breakdown_compare_groups(
        self, current_groups: list[list[dict[str, Any]]], previous_groups: list[list[dict[str, Any]]]
    ) -> list[list[dict[str, Any]]]:
        """Tag each breakdown inner funnel with its period and return the combined 2·N list, aligned
        by breakdown value. A value present in only one period is still represented on the other
        side as a zeroed inner funnel (preserving its breakdown_value), so the chart can draw a
        current/previous pair for every value. Emits all current groups, then all previous groups."""
        current_by_value = {self._breakdown_key(group): group for group in current_groups}
        previous_by_value = {self._breakdown_key(group): group for group in previous_groups}

        # Current values first (the runner already ordered them by count), then previous-only values.
        ordered_keys = list(current_by_value.keys()) + [key for key in previous_by_value if key not in current_by_value]

        def tagged(group: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
            return [{**step, "compare_label": label} for step in group]

        merged: list[list[dict[str, Any]]] = []
        for key in ordered_keys:
            current_group = current_by_value.get(key) or self._zeroed_steps_skeleton(previous_by_value[key])
            merged.append(tagged(current_group, "current"))
        for key in ordered_keys:
            previous_group = previous_by_value.get(key) or self._zeroed_steps_skeleton(current_by_value[key])
            merged.append(tagged(previous_group, "previous"))
        return merged

    def _calculate_compare_time_to_convert(self) -> FunnelsQueryResponse:
        """Compare for the TIME_TO_CONVERT viz: both histograms must share an x-axis.

        Step 1 computes the bin boundaries from the union of conversion times observed across
        both periods. Step 2 runs both `FunnelTimeToConvertUDF` queries in parallel, each pinned
        to those shared boundaries. The merged result is a two-element list (current + previous),
        each tagged with `compare_label` and carrying `bins`/`average_conversion_time` aligned on
        the shared boundaries.
        """
        current_funnel = self.funnel_class
        previous_funnel = self._build_previous_funnel()

        current_bounds, previous_bounds = self._run_in_parallel(
            [
                lambda timings: self._run_time_to_convert_bounds(current_funnel, timings),
                lambda timings: self._run_time_to_convert_bounds(previous_funnel, timings),
            ]
        )
        boundaries = compute_shared_bin_boundaries(current_bounds, previous_bounds, self.context.funnelsFilter.binCount)

        current_result, previous_result = self._run_in_parallel(
            [
                lambda timings: self._run_time_to_convert_histogram(current_funnel, boundaries, timings),
                lambda timings: self._run_time_to_convert_histogram(previous_funnel, boundaries, timings),
            ],
            index_offset=2,
        )

        merged_results = [
            {**current_result.model_dump(), "compare_label": "current"},
            {**previous_result.model_dump(), "compare_label": "previous"},
        ]

        return FunnelsQueryResponse(
            results=merged_results,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )

    def _run_time_to_convert_bounds(
        self, funnel: FunnelTimeToConvertUDF, timings: HogQLTimings
    ) -> Optional[ConversionTimeRange]:
        response = self._execute_funnel_query(funnel.get_bounds_query(), timings)
        if not response.results:
            return None
        sample_count, min_timing, max_timing = response.results[0]
        if not sample_count:
            return None
        return ConversionTimeRange(min_timing=min_timing, max_timing=max_timing, sample_count=sample_count)

    def _run_time_to_convert_histogram(
        self, funnel: FunnelTimeToConvertUDF, boundaries: list[int], timings: HogQLTimings
    ) -> FunnelTimeToConvertResults:
        if not boundaries:
            # Neither period converted — return an empty histogram skeleton.
            return FunnelTimeToConvertResults(bins=[], average_conversion_time=None)
        response = self._execute_funnel_query(funnel.get_query(explicit_bins=boundaries), timings)
        return funnel._format_results(response.results)

    def _execute_funnel_query(self, query: ast.SelectQuery, timings: HogQLTimings):
        return execute_hogql_query(
            query_type="FunnelsQuery",
            query=query,
            team=self.team,
            user=self.user,
            timings=timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            settings=HogQLGlobalSettings(
                # Make sure funnel queries never OOM
                max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
            ),
        )

    def _build_previous_funnel(self):
        """Construct a funnel (matching the current viz mode) pinned to the previous-period range."""
        return self._funnel_class_for_context(self._previous_period_context())

    def _previous_period_context(self) -> FunnelQueryContext:
        """A query context pinned to the previous-period range.

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
        return FunnelQueryContext(
            query=previous_query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

    def _funnel_class_for_context(self, context: FunnelQueryContext):
        funnelVizType = context.funnelsFilter.funnelVizType
        if funnelVizType == FunnelVizType.TRENDS:
            return FunnelTrendsUDF(context=context, just_summarize=self.just_summarize)
        elif funnelVizType == FunnelVizType.TIME_TO_CONVERT:
            return FunnelTimeToConvertUDF(context=context)
        return FunnelUDF(context=context)

    def _actor_class_for_context(self, context: FunnelQueryContext):
        # Actors for TIME_TO_CONVERT come from the plain step funnel (FunnelUDF), not the histogram class.
        if context.funnelsFilter.funnelVizType == FunnelVizType.TRENDS:
            return FunnelTrendsUDF(context=context)
        return FunnelUDF(context=context)

    def _is_compare_active(self) -> bool:
        compare_filter = self.query.compareFilter
        if compare_filter is None or not compare_filter.compare:
            return False
        # Compare is supported for the STEPS, TRENDS and TIME_TO_CONVERT viz modes. FLOW is excluded.
        if self.context.funnelsFilter.funnelVizType not in (
            FunnelVizType.STEPS,
            FunnelVizType.TRENDS,
            FunnelVizType.TIME_TO_CONVERT,
        ):
            return False
        return self._team_flag_funnels_compare()

    def _team_flag_funnels_compare(self) -> bool:
        return feature_enabled_or_false(
            "product-analytics-funnels-compare",
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
        return self._actor_class_for_context(self.context)

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

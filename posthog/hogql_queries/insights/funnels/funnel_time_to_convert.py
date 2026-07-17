from typing import cast

from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelTimeToConvertResults

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.constants import FUNNEL_TO_STEP
from posthog.hogql_queries.insights.funnels import FunnelUDF
from posthog.hogql_queries.insights.funnels.base import FunnelBase
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext


class FunnelTimeToConvertUDF(FunnelBase):
    def __init__(
        self,
        context: FunnelQueryContext,
    ):
        super().__init__(context)

        self.funnel_order: FunnelUDF = FunnelUDF(context=self.context)

    def _format_results(self, results: list) -> FunnelTimeToConvertResults:
        return FunnelTimeToConvertResults(
            bins=[[bin_from_seconds, person_count] for bin_from_seconds, person_count, _, _ in results],
            average_conversion_time=results[0][2],
            median_conversion_time=results[0][3],
        )

    def _from_to_steps(self) -> tuple[int, int]:
        query, funnelsFilter = self.context.query, self.context.funnelsFilter
        # Conversion from which step should be calculated
        from_step = funnelsFilter.funnelFromStep or 0
        # Conversion to which step should be calculated
        to_step = funnelsFilter.funnelToStep or len(query.series) - 1

        if not (0 < to_step < len(query.series)):
            raise ValidationError(
                f"Filter parameter {FUNNEL_TO_STEP} can only be one of {', '.join(map(str, range(1, len(query.series))))} for time to convert!"
            )
        return from_step, to_step

    def _conversion_timings_query(self) -> ast.SelectQuery:
        """The per-person conversion times (`timings` array) for the from→to step range."""
        from_step, to_step = self._from_to_steps()
        inner_select = self.funnel_order._inner_aggregation_query()
        return cast(
            ast.SelectQuery,
            parse_select(
                f"""
                SELECT
                    groupArray(arraySum(arraySlice(timings, {from_step + 1}, {to_step - from_step}))) as timings
                FROM {{inner_select}}
                WHERE step_reached >= {to_step}""",
                {"inner_select": inner_select},
            ),
        )

    def get_bounds_query(self) -> ast.SelectQuery:
        """Sample count and min/max conversion time for this period — feeds the shared-bin computer."""
        return cast(
            ast.SelectQuery,
            parse_select(
                """
                SELECT
                    length(timings) as sample_count,
                    if(sample_count > 0, floor(arrayMin(timings)), 0) as min_timing,
                    if(sample_count > 0, ceil(arrayMax(timings)), 0) as max_timing
                FROM {timings}""",
                {"timings": self._conversion_timings_query()},
            ),
        )

    def get_query(self, explicit_bins: list[int] | None = None) -> ast.SelectQuery:
        funnelsFilter = self.context.funnelsFilter
        timings_query = self._conversion_timings_query()

        if explicit_bins is not None:
            # Compare passes shared boundaries so both periods land on the same x-axis. Derive the
            # equal-width parameters from them and skip the per-period min/max inference below.
            bin_count = len(explicit_bins) - 1
            min_timing = explicit_bins[0]
            bin_width = explicit_bins[1] - explicit_bins[0] if bin_count > 0 else 60
            bin_setup = f"""
                {bin_count} as bin_count,
                {min_timing} as min_timing,
                {bin_width} as bin_width_seconds,"""
        else:
            # Use custom bin_count if provided by user, otherwise infer one from the number of samples
            binCount = funnelsFilter.binCount
            if binCount is not None:
                # Custom count is clamped between 1 and 90
                if binCount < 1:
                    binCount = 1
                elif binCount > 90:
                    binCount = 90
                bin_count_expression = f"""{binCount}"""
            else:
                # Auto count is clamped between 1 and 60
                bin_count_expression = f"""toInt(least(60, greatest(1, ceil(cbrt(ifNull(length(timings), 0))))))"""
            bin_setup = f"""
                {bin_count_expression} as bin_count,
                floor(arrayMin(timings)) as min_timing,
                ceil(arrayMax(timings)) as max_timing,
                ceil((max_timing - min_timing) / bin_count) as bin_width_seconds_raw,
                if(bin_width_seconds_raw > 0, bin_width_seconds_raw, 60) AS bin_width_seconds,"""

        # nosemgrep: hogql-fstring-audit (interpolated values are internal ints; {{timings}} is a HogQL placeholder)
        bins = parse_select(
            f"""
            SELECT
                timings,
                {bin_setup}
                arrayMap(n -> toInt(round(min_timing + n * bin_width_seconds)), range(0, bin_count + 1)) as buckets,
                arrayMap(timing -> toInt(floor((timing - min_timing) / bin_width_seconds)), timings) as indices,
                arrayMap(x -> countEqual(indices, x-1), range(1, bin_count + 2)) as counts
            FROM {{timings}}""",
            {"timings": timings_query},
        )

        return cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                bin_from_seconds,
                person_count,
                arrayAvg(timings) as averageConversionTime,
                arrayMap(x -> if(isNaN(x), NULL, x), [arrayReduce('median', timings)])[1] as medianConversionTime
            FROM {bins}
            ARRAY JOIN
            counts as person_count,
            buckets as bin_from_seconds
            """,
                {"bins": bins},
            ),
        )

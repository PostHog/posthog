from typing import cast

from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelTimeToConvertResults, StepOrderValue

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.constants import FUNNEL_TO_STEP
from posthog.hogql_queries.insights.funnels import FunnelTimeToConvert, FunnelUDF
from posthog.hogql_queries.insights.funnels.base import FunnelBase
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.utils import get_funnel_order_class


class FunnelTimeToConvertUDF(FunnelBase):
    def __init__(
        self,
        context: FunnelQueryContext,
    ):
        super().__init__(context)

        self.funnel_order: FunnelUDF = get_funnel_order_class(self.context.funnelsFilter, use_udf=True)(
            context=self.context
        )

    def _format_results(self, results: list) -> FunnelTimeToConvertResults:
        return FunnelTimeToConvertResults(
            bins=[[bin_from_seconds, person_count] for bin_from_seconds, person_count, _ in results],
            average_conversion_time=results[0][2],
        )

    def get_query(self) -> ast.SelectQuery:
        query, funnelsFilter = self.context.query, self.context.funnelsFilter
        if funnelsFilter.funnelOrderType == StepOrderValue.UNORDERED:
            # Currently don't support unordered in UDFs
            return FunnelTimeToConvert(self.context).get_query()

        # Conversion from which step should be calculated
        from_step = funnelsFilter.funnelFromStep or 0
        # Conversion to which step should be calculated
        to_step = funnelsFilter.funnelToStep or len(query.series) - 1

        # Use custom bin_count if provided by user, otherwise infer an automatic one based on the number of samples
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

        if not (0 < to_step < len(query.series)):
            raise ValidationError(
                f'Filter parameter {FUNNEL_TO_STEP} can only be one of {", ".join(map(str, range(1, len(query.series))))} for time to convert!'
            )

        inner_select = self.funnel_order._inner_aggregation_query()

        timings = parse_select(
            f"""
            SELECT
                groupArray(arraySum(arraySlice(timings, {from_step+1}, {to_step - from_step}))) as timings,
                {bin_count_expression} as bin_count,
                floor(arrayMin(timings)) as min_timing,
                ceil(arrayMax(timings)) as max_timing,
                ceil((max_timing - min_timing) / bin_count) as bin_width_seconds_raw,
                if(bin_width_seconds_raw > 0, bin_width_seconds_raw, 60) AS bin_width_seconds,
                arrayMap(n -> toInt(round(min_timing + n * bin_width_seconds)), range(0, bin_count + 1)) as buckets,
                arrayMap(timing -> toInt(floor((timing - min_timing) / bin_width_seconds)), timings) as indices,
                arrayMap(x -> countEqual(indices, x-1), range(1, bin_count + 2)) as counts
            FROM {{inner_select}}
            WHERE step_reached >= {to_step}""",
            {"inner_select": inner_select},
        )

        return cast(
            ast.SelectQuery,
            parse_select(
                f"""
            SELECT
                bin_from_seconds,
                person_count,
                arrayAvg(timings) as averageConversionTime
            FROM {{timings}}
            ARRAY JOIN
            counts as person_count,
            buckets as bin_from_seconds
            """,
                {"timings": timings},
            ),
        )

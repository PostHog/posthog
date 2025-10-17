from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelTimeToConvertResults

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.constants import FUNNEL_TO_STEP
from posthog.hogql_queries.insights.funnels.base import FunnelBase
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.utils import get_funnel_order_class


class FunnelTimeToConvert(FunnelBase):
    def __init__(
        self,
        context: FunnelQueryContext,
    ):
        super().__init__(context)

        # Haven't implemented calls for time_to_convert in UDF yet
        self.funnel_order = get_funnel_order_class(self.context.funnelsFilter, use_udf=False)(context=self.context)

    def _format_results(self, results: list) -> FunnelTimeToConvertResults:
        return FunnelTimeToConvertResults(
            bins=[[bin_from_seconds, person_count] for bin_from_seconds, person_count, _ in results],
            average_conversion_time=results[0][2],
        )

    def get_query(self) -> ast.SelectQuery:
        query, funnelsFilter = self.context.query, self.context.funnelsFilter

        steps_per_person_query = self.funnel_order.get_step_counts_query()
        # expects 1 person per row, whatever their max step is, and the step conversion times for this person

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
            bin_count_identifier = str(binCount)
            bin_count_expression = None
        else:
            # Auto count is clamped between 1 and 60
            bin_count_identifier = "bin_count"
            bin_count_expression = f"""
                count() AS sample_count,
                least(60, greatest(1, ceil(cbrt(ifNull(sample_count, 0))))) AS {bin_count_identifier},
            """

        if not (0 < to_step < len(query.series)):
            raise ValidationError(
                f'Filter parameter {FUNNEL_TO_STEP} can only be one of {", ".join(map(str, range(1, len(query.series))))} for time to convert!'
            )

        steps_average_conversion_time_identifiers = [
            f"step_{step+1}_average_conversion_time_inner" for step in range(from_step, to_step)
        ]
        steps_average_conversion_time_expression_sum = " + ".join(steps_average_conversion_time_identifiers)

        time_to_convert_query = parse_select(
            f"""
            WITH
                step_runs AS (
                    {{steps_per_person_query}}
                ),
                histogram_params AS (
                    /* Binning ensures that each sample belongs to a bin in results */
                    /* If bin_count is not a custom number, it's calculated in bin_count_expression */
                    SELECT
                        ifNull(floor(min({steps_average_conversion_time_expression_sum})), 0) AS from_seconds,
                        ifNull(ceil(max({steps_average_conversion_time_expression_sum})), 1) AS to_seconds,
                        round(avg({steps_average_conversion_time_expression_sum}), 2) AS average_conversion_time,
                        {bin_count_expression or ""}
                        ceil((to_seconds - from_seconds) / {bin_count_identifier}) AS bin_width_seconds_raw,
                        /* Use 60 seconds as fallback bin width in case of only one sample */
                        if(bin_width_seconds_raw > 0, bin_width_seconds_raw, 60) AS bin_width_seconds
                    FROM step_runs
                    -- We only need to check step to_step here, because it depends on all the other ones being NOT NULL too
                    WHERE step_{to_step}_average_conversion_time_inner IS NOT NULL
                ),
                /* Below CTEs make histogram_params columns available to the query below as straightforward identifiers */
                ( SELECT bin_width_seconds FROM histogram_params ) AS bin_width_seconds,
                /* bin_count is only made available as an identifier if it had to be calculated */
                {
                    f"( SELECT {bin_count_identifier} FROM histogram_params ) AS {bin_count_identifier},"
                    if bin_count_expression else ""
                }
                ( SELECT from_seconds FROM histogram_params ) AS histogram_from_seconds,
                ( SELECT to_seconds FROM histogram_params ) AS histogram_to_seconds,
                ( SELECT average_conversion_time FROM histogram_params ) AS histogram_average_conversion_time
            SELECT
                fill.bin_from_seconds,
                person_count,
                histogram_average_conversion_time AS average_conversion_time
            FROM (
                /* Calculating bins from step runs */
                SELECT
                    histogram_from_seconds + floor(({steps_average_conversion_time_expression_sum} - histogram_from_seconds) / bin_width_seconds) * bin_width_seconds AS bin_from_seconds,
                    count() AS person_count
                FROM step_runs
                GROUP BY bin_from_seconds
            ) results
            RIGHT OUTER JOIN (
                /* Making sure bin_count bins are returned */
                /* Those not present in the results query due to lack of data simply get person_count 0 */
                SELECT histogram_from_seconds + number * bin_width_seconds AS bin_from_seconds FROM numbers(ifNull({bin_count_identifier}, 0) + 1)
            ) fill
            -- USING (bin_from_seconds)
            ON results.bin_from_seconds = fill.bin_from_seconds
            -- ORDER BY bin_from_seconds
            ORDER BY fill.bin_from_seconds
        """,
            placeholders={"steps_per_person_query": steps_per_person_query},
        )

        assert isinstance(time_to_convert_query, ast.SelectQuery)
        return time_to_convert_query

from rest_framework.exceptions import ValidationError

from posthog.constants import FUNNEL_TO_STEP
from posthog.models.filters.filter import Filter
from posthog.models.team import Team
from posthog.queries.funnels.base import ClickhouseFunnelBase
from posthog.queries.funnels.utils import get_funnel_order_class


class ClickhouseFunnelTimeToConvert(ClickhouseFunnelBase):
    QUERY_TYPE = "funnel_time_to_convert"

    def __init__(self, filter: Filter, team: Team) -> None:
        super().__init__(filter, team)
        self.funnel_order = get_funnel_order_class(filter)(filter, team)

    def _format_results(self, results: list) -> dict:
        return {
            "bins": [(bin_from_seconds, person_count) for bin_from_seconds, person_count, _ in results],
            "average_conversion_time": results[0][2],
        }

    def get_query(self) -> str:
        steps_per_person_query = self.funnel_order.get_step_counts_query()
        self.params.update(self.funnel_order.params)
        # expects 1 person per row, whatever their max step is, and the step conversion times for this person

        # Conversion from which step should be calculated
        from_step = self._filter.funnel_from_step or 0
        # Conversion to which step should be calculated
        to_step = self._filter.funnel_to_step or len(self._filter.entities) - 1

        # Use custom bin_count if provided by user, otherwise infer an automatic one based on the number of samples
        bin_count = self._filter.bin_count
        if bin_count is not None:
            # Custom count is clamped between 1 and 90
            if bin_count < 1:
                bin_count = 1
            elif bin_count > 90:
                bin_count = 90
            bin_count_identifier = str(bin_count)
            bin_count_expression = None
        else:
            # Auto count is clamped between 1 and 60
            bin_count_identifier = "bin_count"
            bin_count_expression = f"""
                count() AS sample_count,
                least(60, greatest(1, ceil(cbrt(ifNull(sample_count, 0))))) AS {bin_count_identifier},
            """

        if not (0 < to_step < len(self._filter.entities)):
            raise ValidationError(
                f'Filter parameter {FUNNEL_TO_STEP} can only be one of {", ".join(map(str, range(1, len(self._filter.entities))))} for time to convert!'
            )

        steps_average_conversion_time_identifiers = [
            f"step_{step+1}_average_conversion_time_inner" for step in range(from_step, to_step)
        ]
        steps_average_conversion_time_expression_sum = " + ".join(steps_average_conversion_time_identifiers)

        query = f"""
            WITH
                step_runs AS (
                    {steps_per_person_query}
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
                bin_from_seconds,
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
                SELECT histogram_from_seconds + number * bin_width_seconds AS bin_from_seconds FROM system.numbers LIMIT ifNull({bin_count_identifier}, 0) + 1
            ) fill
            USING (bin_from_seconds)
            ORDER BY bin_from_seconds
            SETTINGS max_ast_elements=1000000, max_expanded_ast_elements=1000000
        """

        return query

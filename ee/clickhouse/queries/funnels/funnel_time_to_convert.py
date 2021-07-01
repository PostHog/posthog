from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnelNew


class ClickhouseFunnelTimeToConvert(ClickhouseFunnelNew):
    def _format_results(self, results: list) -> list:
        return results

    def get_query(self, format_properties) -> str:
        steps_per_person_query = self._get_steps_per_person_query()

        # Conversion to which step (from the immediately preceding one) should be calculated
        to_step = self._filter.funnel_to_step
        # How many bins should we try to calculate
        number_of_bins = 10

        if not (0 < to_step < len(self._filter.entities)):
            raise ValueError(
                f'Filter parameter funnel_to_step can only be one of {", ".join(map(str, range(1, len(self._filter.entities))))} for time to convert!'
            )

        query = f"""
            WITH step_runs AS (
                {steps_per_person_query}
            ), (
                -- Automatic bin interval which makes sure that there's always number_of_bins bins
                -- and that each step run will belong to one bin in results
                SELECT ceil(max(step_{to_step}_average_conversion_time) / {number_of_bins}) AS bin_base_seconds FROM step_runs
            ) AS bin_base_seconds
            SELECT
                bin_to_seconds,
                person_count
            FROM (
                -- Calculating bins from step runs
                SELECT
                    floor(step_{to_step}_average_conversion_time / bin_base_seconds + 1) * bin_base_seconds AS bin_to_seconds,
                    count() AS person_count
                FROM step_runs
                WHERE step_{to_step}_average_conversion_time IS NOT NULL
                GROUP BY bin_to_seconds
            ) results
            FULL OUTER JOIN (
                -- Making sure number_of_bins bins are returned
                -- Those not present in the results query due to lack of data simply get person_count 0
                SELECT (number + 1) * bin_base_seconds AS bin_to_seconds FROM numbers({number_of_bins})
            ) fill
            USING (bin_to_seconds)
            ORDER BY bin_to_seconds
            SETTINGS allow_experimental_window_functions = 1"""

        return query

from datetime import date, datetime, timedelta
from typing import Union

from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnelNew
from ee.clickhouse.queries.util import get_time_diff, get_trunc_func_ch

DAY_START = 0
TOTAL_COMPLETED_FUNNELS = 1
ALL_FUNNELS_ENTRIES = 2
PERSON_IDS = 3
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%a. %-d %b"


class ClickhouseFunnelTimeToConvert(ClickhouseFunnelNew):
    def run(self, *args, **kwargs) -> list:
        if len(self._filter.entities) == 0:
            return []

        return self.perform_query()

    def perform_query(self):
        return self._exec_query()

    def get_query(self, format_properties) -> str:
        steps_per_person_query = self._get_steps_per_person_query()

        to_step = (
            self._filter.funnel_to_step
        )  # Conversion to which step (from the immediately preceding one) should be calculated
        number_of_bins = 10  # How many bins should we try to calculate

        if not (0 < to_step < len(self._filter.entities)):
            raise ValueError(
                f'Filter parameter funnel_to_step can only be one of {", ".join(map(str, range(1, len(self._filter.entities))))} for time to convert!'
            )

        query = f"""
            SELECT histogram_tuples.1 AS bin_from_seconds, histogram_tuples.2 AS bin_to_seconds, histogram_tuples.3 AS weight FROM (
                SELECT arrayJoin(histogram({number_of_bins})(step_{to_step}_average_conversion_time)) AS histogram_tuples FROM (
                    {steps_per_person_query}
                )
            )
            SETTINGS allow_experimental_window_functions = 1"""

        return query

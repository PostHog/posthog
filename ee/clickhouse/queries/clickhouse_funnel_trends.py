# [x] Move query logic to here
# [x] Get test framework working
# [x] Change assertions normal assertions
# [ ] Convert query results to interval (hours, partial days, days, weeks, months, years)
# [ ] Follow existing code patterns (Integrate filter class)
from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.funnels.funnel_trend import FUNNEL_TREND_SQL


class ClickhouseFunnelTrends:
    @staticmethod
    def _run_query(format_dictionary):
        query = FUNNEL_TREND_SQL.format(**format_dictionary)
        results = sync_execute(query, {})
        return results

    @staticmethod
    def _milliseconds_from_days(days):
        second, minute, hour, day = [1000, 60, 60, 24]
        return second * minute * hour * day * days

    def run(self, format_dictionary):
        return self._run_query(format_dictionary)

    @staticmethod
    def _convert_to_users(results):
        my_dict = dict()
        for index, value in enumerate(results):
            [date, distinct_id, max_step] = value
            if distinct_id in my_dict:
                my_dict[distinct_id]["dates"].append(date)
            elif distinct_id:
                my_dict[distinct_id] = {
                    "distinct_id": distinct_id,
                    "max_step": max_step,
                    "dates": [date],
                }
        return my_dict

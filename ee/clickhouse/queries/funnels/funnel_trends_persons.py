from datetime import datetime

from ee.clickhouse.queries.funnels.funnel_trends import TIMESTAMP_FORMAT, ClickhouseFunnelTrends
from ee.clickhouse.queries.util import get_trunc_func_ch
from posthog.models.person import Person


class ClickhouseFunnelTrendsPersons(ClickhouseFunnelTrends):
    PAGE_SIZE = 100

    def get_query(self) -> str:
        steps_per_person_query = self.get_step_counts_without_aggregation_query()
        # Expects multiple rows for same person, first event time, steps taken.
        self.params.update(self.funnel_order.params)

        (
            reached_from_step_count_condition,
            reached_to_step_count_condition,
            did_not_reach_to_step_count_condition,
        ) = self.get_steps_reached_conditions()
        interval_method = get_trunc_func_ch(self._filter.interval)

        for_entrance_period_start: datetime = datetime(1970, 1, 1)  # TODO
        droped_off: bool = False  # TODO
        page_index: int = 0  # TODO

        query = f"""
            SELECT
                person_id,
                {interval_method}(timestamp) AS entrance_period_start,
                min(timestamp) AS first_entrance
                max(steps) AS steps_completed
            FROM (
                {steps_per_person_query}
            ) GROUP BY person_id, entrance_period_start
            WHERE
                for_entrance_period_start = {for_entrance_period_start.strftime(TIMESTAMP_FORMAT)}
                AND {did_not_reach_to_step_count_condition if droped_off else reached_to_step_count_condition}
            ORDER BY person_id
            LIMIT {self.PAGE_SIZE}
            OFFSET {self.PAGE_SIZE * page_index}
            SETTINGS allow_experimental_window_functions = 1"""

        return query

    def _format_results(self, results):
        people = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data

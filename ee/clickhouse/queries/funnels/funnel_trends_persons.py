from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.funnels.funnel_trends import TIMESTAMP_FORMAT, ClickhouseFunnelTrends
from ee.clickhouse.queries.util import get_trunc_func_ch
from posthog.constants import DROP_OFF, ENTRANCE_PERIOD_START, OFFSET
from posthog.models.person import Person


class ClickhouseFunnelTrendsPersons(ClickhouseFunnelTrends):
    def get_query(self) -> str:
        steps_per_person_query = self.funnel_order.get_step_counts_without_aggregation_query()
        # Expects multiple rows for same person, first event time, steps taken.
        self.params.update(self.funnel_order.params)

        _, reached_to_step_count_condition, did_not_reach_to_step_count_condition = self.get_steps_reached_conditions()
        interval_method = get_trunc_func_ch(self._filter.interval)

        drop_off = self._filter.drop_off
        if drop_off is None:
            raise ValidationError(f"Filter parameter {DROP_OFF} must be provided and a bool for funnel trends persons!")
        entrance_period_start = self._filter.entrance_period_start
        if not entrance_period_start:
            raise ValidationError(
                f"Filter parameter {ENTRANCE_PERIOD_START} must be provided and a datetime for funnel trends persons!"
            )
        self.params[ENTRANCE_PERIOD_START] = entrance_period_start.strftime(TIMESTAMP_FORMAT)
        self.params[OFFSET] = self._filter.offset

        query = f"""
            SELECT
                person_id,
                {interval_method}(timestamp) AS entrance_period_start,
                max(steps) AS steps_completed
            FROM (
                {steps_per_person_query}
            )
            WHERE entrance_period_start = %({ENTRANCE_PERIOD_START})s
            GROUP BY person_id, entrance_period_start
            HAVING {did_not_reach_to_step_count_condition if drop_off else reached_to_step_count_condition}
            ORDER BY person_id
            LIMIT 100
            OFFSET %({OFFSET})s
            SETTINGS allow_experimental_window_functions = 1"""

        return query

    def _summarize_data(self, results):
        return results

    def _format_results(self, results):
        people = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data

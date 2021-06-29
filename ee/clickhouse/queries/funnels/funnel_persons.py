from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models import Person


class ClickhouseFunnelPersons(ClickhouseFunnelBase):
    def get_query(self, format_properties):
        steps_per_person_query = self._get_steps_per_person_query()
        return FUNNEL_PERSONS_BY_STEP_SQL.format(
            **format_properties,
            steps_per_person_query=steps_per_person_query,
            persons_steps=self._get_funnel_person_step_condition()
        )

    def _get_funnel_person_step_condition(self):
        step_num = self._filter.funnel_step
        max_steps = len(self._filter.entities)

        if step_num is None:
            raise ValueError("funnel_step should not be none")

        if step_num >= 0:
            self.params.update({"step_num": [i for i in range(step_num, max_steps + 1)]})
            return "steps IN %(step_num)s"
        else:
            self.params.update({"step_num": abs(step_num) - 1})
            return "steps = %(step_num)s"

    def _format_results(self, results):
        formatted_results = []
        for row in results:
            distinct_ids, email = Person.get_distinct_ids_and_email_by_id(row[0], self._team.id)
            formatted_results.append({"max_step": row[0], "distinct_ids": distinct_ids, "email": email})
        return formatted_results

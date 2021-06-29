from ee.clickhouse.queries.funnels.funnel_unordered import ClickhouseFunnelUnordered
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_BY_STEP_SQL
from posthog.models import Person


class ClickhouseFunnelUnorderedPersons(ClickhouseFunnelUnordered):
    def get_query(self, format_properties):
        return FUNNEL_PERSONS_BY_STEP_SQL.format(
            **format_properties,
            steps_per_person_query=self.get_step_counts_query(),
            persons_steps=self._get_funnel_person_step_condition()
        )

    def _format_results(self, results):
        formatted_results = []
        for row in results:
            distinct_ids, email = Person.get_distinct_ids_and_email_by_id(row[0])
            formatted_results.append({"max_step": row[1], "distinct_ids": distinct_ids, "email": email})
        return formatted_results

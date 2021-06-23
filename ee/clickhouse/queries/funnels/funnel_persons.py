from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_SQL
from posthog.models import Person


class ClickhouseFunnelPersons(ClickhouseFunnelBase):
    def get_query(self, format_properties):
        return FUNNEL_PERSONS_SQL.format(**format_properties)

    def _format_results(self, results):
        formatted_results = []
        for row in results:
            distinct_ids, email = Person.get_distinct_ids_and_email_by_id(row[1], self._team.id)
            formatted_results.append({"max_step": row[0], "distinct_ids": distinct_ids, "email": email})
        return formatted_results

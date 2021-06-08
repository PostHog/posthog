from typing import Any, Dict, List, Tuple

from django.utils import timezone

from ee.clickhouse.client import format_sql, sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.clickhouse_funnel_base import ClickhouseFunnelBase
from ee.clickhouse.queries.clickhouse_funnel_trends import ClickhouseFunnelTrends
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.funnels.funnel import FUNNEL_SQL
from ee.clickhouse.sql.person import GET_LATEST_PERSON_DISTINCT_ID_SQL
from posthog.constants import TRENDS_LINEAR
from posthog.utils import relative_date_parse


class ClickhouseFunnel(ClickhouseFunnelBase):
    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        if len(self._filter.entities) == 0:
            return []

        if self._filter.display == TRENDS_LINEAR:
            return ClickhouseFunnelTrends(self._filter, self._team).run()
        else:
            # Format of this is [step order, person count (that reached that step), array of person uuids]
            results = self._exec_query()

            steps = []
            relevant_people = []
            total_people = 0

            for step in reversed(self._filter.entities):
                # Clickhouse step order starts at one, hence the +1
                result_step = [x for x in results if step.order + 1 == x[0]]
                if len(result_step) > 0:
                    total_people += result_step[0][1]
                    relevant_people += result_step[0][2]
                steps.append(self._serialize_step(step, total_people, relevant_people[0:100]))

            return steps[::-1]  #  reverse

    def _exec_query(self) -> List[Tuple]:
        prop_filters, prop_filter_params = parse_prop_clauses(
            self._filter.properties,
            self._team.pk,
            prepend="global",
            allow_denormalized_props=True,
            filter_test_accounts=self._filter.filter_test_accounts,
        )

        # format default dates
        data = {}
        if not self._filter._date_from:
            data.update({"date_from": relative_date_parse("-7d")})
        if not self._filter._date_to:
            data.update({"date_to": timezone.now()})
        self._filter = self._filter.with_data(data)

        parsed_date_from, parsed_date_to, _ = parse_timestamps(
            filter=self._filter, table="events.", team_id=self._team.pk
        )
        self.params.update(prop_filter_params)
        steps = [self._build_steps_query(entity, index) for index, entity in enumerate(self._filter.entities)]
        query = FUNNEL_SQL.format(
            team_id=self._team.id,
            steps=", ".join(steps),
            filters=prop_filters.replace("uuid IN", "events.uuid IN", 1),
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            top_level_groupby="",
            extra_select="",
            extra_groupby="",
            within_time="6048000000000000",
            latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
        )
        return sync_execute(query, self.params)

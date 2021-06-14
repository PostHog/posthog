from typing import Any, Dict, List, Tuple

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.funnels.clickhouse_funnel_base import ClickhouseFunnelBase
from ee.clickhouse.queries.funnels.clickhouse_funnel_trends import ClickhouseFunnelTrends
from ee.clickhouse.queries.funnels.funnel_event_query import FunnelEventQuery
from ee.clickhouse.sql.funnels.funnel import FUNNEL_SQL
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
        # format default dates
        data = {}
        if not self._filter._date_from:
            data.update({"date_from": relative_date_parse("-7d")})
        if not self._filter._date_to:
            data.update({"date_to": timezone.now()})
        self._filter = self._filter.with_data(data)

        event_query, event_params = FunnelEventQuery(self._filter, self._team.pk).get_query()
        self.params.update(event_params)

        steps = [self._build_steps_query(entity, index) for index, entity in enumerate(self._filter.entities)]
        query = FUNNEL_SQL.format(
            team_id=self._team.id, steps=", ".join(steps), within_time="6048000000000000", event_query=event_query
        )
        return sync_execute(query, self.params)

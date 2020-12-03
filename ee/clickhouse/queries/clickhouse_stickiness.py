from typing import Any, Dict, Optional

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.stickiness.stickiness import STICKINESS_SQL
from ee.clickhouse.sql.stickiness.stickiness_actions import STICKINESS_ACTIONS_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.queries.stickiness import Stickiness


class ClickhouseStickiness(Stickiness):
    def stickiness(self, entity: Entity, filter: Filter, team_id: int) -> Dict[str, Any]:
        if not filter.date_to or not filter.date_from:
            raise ValueError("_stickiness needs date_to and date_from set")
        range_days = (filter.date_to - filter.date_from).days + 2

        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team_id)

        params: Dict = {"team_id": team_id}
        params = {**params, **prop_filter_params}
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, action_params = format_action_filter(action)
            if action_query == "":
                return {}

            params = {**params, **action_params}
            content_sql = STICKINESS_ACTIONS_SQL.format(
                team_id=team_id,
                actions_query=action_query,
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
                filters=prop_filters,
            )
        else:
            content_sql = STICKINESS_SQL.format(
                team_id=team_id,
                event=entity.id,
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
                filters=prop_filters,
            )

        counts = sync_execute(content_sql, params)
        return self.process_result(counts, range_days)

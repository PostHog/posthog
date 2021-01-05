from typing import Any, Dict, Optional, Tuple

from rest_framework.utils.serializer_helpers import ReturnDict

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.person import ClickhousePersonSerializer
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.person import GET_LATEST_PERSON_SQL, PEOPLE_SQL
from ee.clickhouse.sql.stickiness.stickiness import STICKINESS_SQL
from ee.clickhouse.sql.stickiness.stickiness_actions import STICKINESS_ACTIONS_SQL
from ee.clickhouse.sql.stickiness.stickiness_people import STICKINESS_PEOPLE_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.queries.stickiness import Stickiness


class ClickhouseStickiness(Stickiness):
    def stickiness(self, entity: Entity, filter: StickinessFilter, team_id: int) -> Dict[str, Any]:

        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=filter, team_id=team_id)
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team_id)
        trunc_func = get_trunc_func_ch(filter.interval)

        params: Dict = {"team_id": team_id}
        params = {**params, **prop_filter_params, "num_intervals": filter.total_intervals}
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
                trunc_func=trunc_func,
            )
        else:
            content_sql = STICKINESS_SQL.format(
                team_id=team_id,
                event=entity.id,
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
                filters=prop_filters,
                trunc_func=trunc_func,
            )

        counts = sync_execute(content_sql, params)
        return self.process_result(counts, filter)

    def _format_entity_filter(self, entity: Entity) -> Tuple[str, Dict]:
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                action = Action.objects.get(pk=entity.id)
                action_query, params = format_action_filter(action)
                entity_filter = "AND {}".format(action_query)

            except Action.DoesNotExist:
                raise ValueError("This action does not exist")
        else:
            entity_filter = "AND event = %(event)s"
            params = {"event": entity.id}

        return entity_filter, params

    def _retrieve_people(self, filter: StickinessFilter, team: Team) -> ReturnDict:

        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=filter, team_id=team.pk)
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)
        entity_sql, entity_params = self._format_entity_filter(entity=filter.target_entity)
        trunc_func = get_trunc_func_ch(filter.interval)

        params: Dict = {
            "team_id": team.pk,
            **prop_filter_params,
            "stickiness_day": filter.selected_interval,
            **entity_params,
            "offset": filter.offset,
        }

        content_sql = STICKINESS_PEOPLE_SQL.format(
            entity_filter=entity_sql,
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            filters=prop_filters,
            trunc_func=trunc_func,
        )

        people = sync_execute(
            PEOPLE_SQL.format(
                content_sql=content_sql, query="", latest_person_sql=GET_LATEST_PERSON_SQL.format(query="")
            ),
            params,
        )
        return ClickhousePersonSerializer(people, many=True).data

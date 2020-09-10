from datetime import datetime, timezone
from itertools import accumulate
from typing import Any, Dict, List

from ee.clickhouse.client import ch_client
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import get_interval_annotation_ch, get_time_diff, parse_timestamps
from ee.clickhouse.sql.events import NULL_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TRENDS_CUMULATIVE
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery, determine_compared_filter
from posthog.utils import relative_date_parse

# TODO: use timezone from timestamp request and not UTC remove from all below—should be localized to requester timezone
VOLUME_SQL = """
SELECT count(*) as total, toDateTime({interval}({timestamp}), 'UTC') as day_start from events where team_id = {team_id} and event = '{event}' {filters} {date_from} {date_to} GROUP BY {interval}({timestamp})
"""

VOLUME_ACTIONS_SQL = """
SELECT count(*) as total, toDateTime({interval}({timestamp}), 'UTC') as day_start from events where team_id = {team_id} and id IN ({actions_query}) {filters} {date_from} {date_to} GROUP BY {interval}({timestamp})
"""

AGGREGATE_SQL = """
SELECT SUM(total), day_start from ({null_sql} UNION ALL {content_sql}) group by day_start order by day_start
"""


class ClickhouseTrends(BaseQuery):
    def _serialize_entity(self, entity: Entity, filter: Filter, team: Team, label_note: str = "") -> Dict[str, Any]:
        serialized: Dict[str, Any] = {
            "action": entity.to_dict(),
            "label": "{}{}".format("{} — ".format(label_note), entity.name),
            "count": 0,
            "data": [],
            "labels": [],
            "days": [],
        }

        # get params
        inteval_annotation = get_interval_annotation_ch(filter.interval)
        num_intervals, seconds_in_interval = get_time_diff(filter.interval or "day", filter.date_from, filter.date_to)

        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)

        prop_filters, prop_filter_params = parse_prop_clauses("id", filter.properties, team)

        # TODO: remove hardcoded params
        params: Dict = {"team_id": team.pk}
        params = {**params, **prop_filter_params}
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, action_params = format_action_filter(action)
            params = {**params, **action_params}
            content_sql = VOLUME_ACTIONS_SQL.format(
                interval=inteval_annotation,
                timestamp="timestamp",
                team_id=team.pk,
                actions_query=action_query,
                date_from=(parsed_date_from or ""),
                date_to=(parsed_date_to or ""),
                filters="AND id IN {filters}".format(filters=prop_filters) if filter.properties else "",
            )
        else:
            content_sql = VOLUME_SQL.format(
                interval=inteval_annotation,
                timestamp="timestamp",
                team_id=team.pk,
                event=entity.id,
                date_from=(parsed_date_from or ""),
                date_to=(parsed_date_to or ""),
                filters="AND id IN {filters}".format(filters=prop_filters) if filter.properties else "",
            )
        null_sql = NULL_SQL.format(
            interval=inteval_annotation, seconds_in_interval=seconds_in_interval, num_intervals=num_intervals
        )

        final_query = AGGREGATE_SQL.format(null_sql=null_sql, content_sql=content_sql)

        result = ch_client.execute(final_query, params)
        counts = [item[0] for item in result]
        dates = [
            item[1].strftime("%Y-%m-%d {}".format("%H:%M" if filter.interval == "hour" else "")) for item in result
        ]
        labels = [
            item[1].strftime("%a. %-d %B {}".format("%I:%M %p" if filter.interval == "hour" else "")) for item in result
        ]
        serialized.update(data=counts, labels=labels, days=dates, count=sum(counts))

        if filter.display == TRENDS_CUMULATIVE:
            serialized.update(data=list(accumulate(counts)))

        return serialized

    def _calculate_trends(self, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        # format default dates
        if not filter._date_from:
            filter._date_from = relative_date_parse("-14d")
        if not filter._date_to:
            filter._date_to = datetime.now(timezone.utc)

        result = []
        for entity in filter.entities:
            if filter.compare:
                compare_filter = determine_compared_filter(filter=filter)
                entity_result = self._serialize_entity(entity, filter, team, "current")
                result.append(entity_result)
                previous_entity_result = self._serialize_entity(entity, compare_filter, team, "previous")
                result.append(previous_entity_result)
            else:
                entity_result = self._serialize_entity(entity, filter, team)
                result.append(entity_result)
        return result

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self._calculate_trends(filter, team)

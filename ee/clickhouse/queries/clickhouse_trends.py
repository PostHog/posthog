import copy
from datetime import datetime, timedelta, timezone
from itertools import accumulate
from typing import Any, Dict, List, Optional, Tuple, Union

from django.db.models.manager import BaseManager

from ee.clickhouse.client import ch_client
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.cohort import format_cohort_table_name
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import get_interval_annotation_ch, get_time_diff, parse_timestamps
from ee.clickhouse.sql.events import NULL_BREAKDOWN_SQL, NULL_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TRENDS_CUMULATIVE
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery, convert_to_comparison, determine_compared_filter
from posthog.utils import relative_date_parse

# TODO: use timezone from timestamp request and not UTC remove from all below—should be localized to requester timezone
VOLUME_SQL = """
SELECT count(*) as total, toDateTime({interval}({timestamp}), 'UTC') as day_start from events where team_id = {team_id} and event = '{event}' {filters} {parsed_date_from} {parsed_date_to} GROUP BY {interval}({timestamp})
"""

VOLUME_ACTIONS_SQL = """
SELECT count(*) as total, toDateTime({interval}({timestamp}), 'UTC') as day_start from events where team_id = {team_id} and id IN ({actions_query}) {filters} {parsed_date_from} {parsed_date_to} GROUP BY {interval}({timestamp})
"""

AGGREGATE_SQL = """
SELECT groupArray(day_start), groupArray(count) FROM (
    SELECT SUM(total) AS count, day_start from ({null_sql} UNION ALL {content_sql}) group by day_start order by day_start
)
"""

TOP_ELEMENTS_ARRAY_OF_KEY_SQL = """
SELECT groupArray(value) FROM (
    SELECT value, count(*) as count 
    FROM 
    events e INNER JOIN
        (
            SELECT *
            FROM events_properties_view AS ep
            WHERE key = %(key)s AND team_id = %(team_id)s
        ) ep ON e.id = ep.event_id WHERE team_id = %(team_id)s {parsed_date_from} {parsed_date_to}
    GROUP BY value
    ORDER BY count DESC
    LIMIT %(limit)s
)
"""

BREAKDOWN_QUERY_SQL = """
SELECT groupArray(day_start), groupArray(count), value FROM (
    SELECT SUM(total) as count, day_start, value FROM (
        SELECT * FROM (
            {null_sql} as main
            CROSS JOIN
                (
                    SELECT value
                    FROM (
                        SELECT %(values)s as value
                    ) ARRAY JOIN value 
                ) as sec
            ORDER BY value, day_start
            UNION ALL 
            SELECT count(*) as total, toDateTime(toStartOfDay(timestamp), 'UTC') as day_start, value
            FROM 
            events e {breakdown_filter}
            GROUP BY day_start, value
        )
    ) 
    GROUP BY day_start, value
    ORDER BY value, day_start
) GROUP BY value
"""

BREAKDOWN_DEFAULT_SQL = """
SELECT groupArray(day_start), groupArray(count) FROM (
    SELECT SUM(total) as count, day_start FROM (
        SELECT * FROM (
            {null_sql} as main
            ORDER BY day_start
            UNION ALL 
            SELECT count(*) as total, toDateTime(toStartOfDay(timestamp), 'UTC') as day_start
            FROM 
            events e {conditions}
            GROUP BY day_start
        )
    ) 
    GROUP BY day_start
    ORDER BY day_start
) 
"""

BREAKDOWN_CONDITIONS_SQL = """
where team_id = %(team_id)s {event_filter} {parsed_date_from} {parsed_date_to} {actions_query}
"""

BREAKDOWN_PROP_JOIN_SQL = """
INNER JOIN (
    SELECT *
    FROM events_properties_view AS ep
    WHERE key = %(key)s and team_id = %(team_id)s
) ep 
ON e.id = ep.event_id where team_id = %(team_id)s {event_filter} {parsed_date_from} {parsed_date_to}
AND value in (%(values)s) {actions_query}
"""

BREAKDOWN_COHORT_JOIN_SQL = """
INNER JOIN (
    {cohort_queries}
) ep
ON e.distinct_id = ep.distinct_id where team_id = %(team_id)s {event_filter} {parsed_date_from} {parsed_date_to} {actions_query}
"""

BREAKDOWN_COHORT_FILTER_SQL = """
SELECT distinct_id, {cohort_pk} as value
FROM person_distinct_id
WHERE person_id IN ({table_name})
"""


class ClickhouseTrends(BaseQuery):
    def _serialize_entity(
        self, entity: Entity, filter: Filter, team: Team, label_note: str = ""
    ) -> List[Dict[str, Any]]:
        serialized: Dict[str, Any] = {
            "action": entity.to_dict(),
            "label": entity.name,
            "count": 0,
            "data": [],
            "labels": [],
            "days": [],
        }
        if filter.breakdown:
            if "all" in filter.breakdown and isinstance(filter.breakdown, list):
                result = []
                filter.breakdown = filter.breakdown if filter.breakdown and isinstance(filter.breakdown, list) else []
                filter.breakdown.remove("all")

                if filter.breakdown:
                    result.extend(self._format_breakdown_query(entity, filter, team))

                filter.breakdown = ["all"]
                all_result = self._format_breakdown_query(entity, filter, team)

                result.extend(all_result)
            else:
                result = self._format_breakdown_query(entity, filter, team)
        else:
            result = self._format_normal_query(entity, filter, team)

        serialized_data = []

        for queried_metric in result:
            serialized_copy = copy.deepcopy(serialized)
            serialized_copy.update(queried_metric)
            serialized_data.append(serialized_copy)

        if filter.display == TRENDS_CUMULATIVE:

            serialized_data = self._handle_cumulative(serialized_data)

        return serialized_data

    def _handle_cumulative(self, entity_metrics: List) -> List[Dict[str, Any]]:
        for metrics in entity_metrics:
            metrics.update(data=list(accumulate(metrics["data"])))
        return entity_metrics

    def _format_breakdown_query(self, entity: Entity, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        params = {"team_id": team.pk}
        inteval_annotation = get_interval_annotation_ch(filter.interval)
        num_intervals, seconds_in_interval = get_time_diff(filter.interval or "day", filter.date_from, filter.date_to)
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)

        action_query = ""
        action_params: Dict = {}

        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, action_params = format_action_filter(action)

        null_sql = NULL_BREAKDOWN_SQL.format(
            interval=inteval_annotation,
            seconds_in_interval=seconds_in_interval,
            num_intervals=num_intervals,
            date_to=((filter.date_to or datetime.now()) + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"),
        )

        if filter.breakdown_type == "cohort":
            breakdown = filter.breakdown if filter.breakdown and isinstance(filter.breakdown, list) else []
            if "all" in breakdown:
                params = {
                    **params,
                    "event": entity.id,
                    **action_params,
                }
                null_sql = NULL_SQL.format(
                    interval=inteval_annotation,
                    seconds_in_interval=seconds_in_interval,
                    num_intervals=num_intervals,
                    date_to=((filter.date_to or datetime.now()) + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"),
                )
                conditions = BREAKDOWN_CONDITIONS_SQL.format(
                    parsed_date_from=parsed_date_from,
                    parsed_date_to=parsed_date_to,
                    actions_query="and id IN ({})".format(action_query) if action_query else "",
                    event_filter="AND event = %(event)s" if not action_query else "",
                )
                breakdown_query = BREAKDOWN_DEFAULT_SQL.format(null_sql=null_sql, conditions=conditions)
            else:
                cohort_queries, cohort_ids = self._format_breakdown_cohort_join_query(breakdown, team)
                params = {
                    **params,
                    "values": cohort_ids,
                    "event": entity.id,
                    **action_params,
                }
                breakdown_filter = BREAKDOWN_COHORT_JOIN_SQL.format(
                    cohort_queries=cohort_queries,
                    parsed_date_from=parsed_date_from,
                    parsed_date_to=parsed_date_to,
                    actions_query="and id IN ({})".format(action_query) if action_query else "",
                    event_filter="AND event = %(event)s" if not action_query else "",
                )
                breakdown_query = BREAKDOWN_QUERY_SQL.format(null_sql=null_sql, breakdown_filter=breakdown_filter)
        elif filter.breakdown_type == "person":
            pass
        else:
            element_params = {**params, "key": filter.breakdown, "limit": 10}
            element_query = TOP_ELEMENTS_ARRAY_OF_KEY_SQL.format(
                parsed_date_from=parsed_date_from, parsed_date_to=parsed_date_to
            )

            try:
                top_elements_array = ch_client.execute(element_query, element_params)
            except:
                top_elements_array = []

            params = {
                **params,
                "values": top_elements_array[0][0],
                "key": filter.breakdown,
                "event": entity.id,
                **action_params,
            }
            breakdown_filter = BREAKDOWN_PROP_JOIN_SQL.format(
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
                actions_query="and id IN ({})".format(action_query) if action_query else "",
                event_filter="AND event = %(event)s" if not action_query else "",
            )
            breakdown_query = BREAKDOWN_QUERY_SQL.format(null_sql=null_sql, breakdown_filter=breakdown_filter)

        try:
            result = ch_client.execute(breakdown_query, params)
        except:
            result = []
        parsed_results = self._parse_breakdown_response(result, filter, entity)
        return parsed_results

    def _format_breakdown_cohort_join_query(self, breakdown: List[Any], team: Team) -> Tuple[str, List]:
        cohorts = Cohort.objects.filter(team_id=team.pk, pk__in=[b for b in breakdown if b != "all"])
        cohort_queries = self._parse_breakdown_cohorts(cohorts)
        ids = [cohort.pk for cohort in cohorts]
        return cohort_queries, ids

    def _parse_breakdown_cohorts(self, cohorts: BaseManager) -> str:
        queries = []
        for cohort in cohorts:
            table_name = format_cohort_table_name(cohort)
            cohort_query = BREAKDOWN_COHORT_FILTER_SQL.format(table_name=table_name, cohort_pk=cohort.pk)
            queries.append(cohort_query)
        return " UNION ALL ".join(queries)

    def _parse_breakdown_response(self, res: List, filter: Filter, entity: Entity) -> List[Dict[str, Any]]:
        parsed = []
        for idx, stats in enumerate(res):
            if filter.breakdown:
                extra_label = self._determine_breakdown_label(filter.breakdown_type, filter.breakdown[idx])
                label = "{} - {}".format(entity.name, extra_label)
                additional_values = {"label": label, "breakdown_value": filter.breakdown[idx]}
            else:
                additional_values = {}
            counts = stats[1]
            dates = [
                ((item - timedelta(days=1)) if filter.interval == "month" else item).strftime(
                    "%Y-%m-%d{}".format(", %H:%M" if filter.interval == "hour" or filter.interval == "minute" else "")
                )
                for item in stats[0]
            ]
            labels = [
                ((item - timedelta(days=1)) if filter.interval == "month" else item).strftime(
                    "%a. %-d %B{}".format(", %H:%M" if filter.interval == "hour" or filter.interval == "minute" else "")
                )
                for item in stats[0]
            ]
            parsed.append({"data": counts, "count": sum(counts), "dates": dates, "labels": labels, **additional_values})

        return parsed

    def _determine_breakdown_label(
        self, breakdown_type: Optional[str], breakdown: Optional[Union[str, int]] = ""
    ) -> str:
        if breakdown_type == "cohort":
            if breakdown == "all":
                return "all users"
            else:
                return Cohort.objects.get(pk=breakdown).name
        elif breakdown_type == "person":
            return ""
        else:
            return str(breakdown) or ""

    def _format_normal_query(self, entity: Entity, filter: Filter, team: Team) -> List[Dict[str, Any]]:

        inteval_annotation = get_interval_annotation_ch(filter.interval)
        num_intervals, seconds_in_interval = get_time_diff(filter.interval or "day", filter.date_from, filter.date_to)
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        prop_filters, prop_filter_params = parse_prop_clauses("id", filter.properties, team)

        params: Dict = {"team_id": team.pk}
        params = {**params, **prop_filter_params}
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                action = Action.objects.get(pk=entity.id)
                action_query, action_params = format_action_filter(action)
                params = {**params, **action_params}
                content_sql = VOLUME_ACTIONS_SQL.format(
                    interval=inteval_annotation,
                    timestamp="timestamp",
                    team_id=team.pk,
                    actions_query=action_query,
                    parsed_date_from=(parsed_date_from or ""),
                    parsed_date_to=(parsed_date_to or ""),
                    filters="{filters}".format(filters=prop_filters) if filter.properties else "",
                )
            except:
                return []
        else:
            content_sql = VOLUME_SQL.format(
                interval=inteval_annotation,
                timestamp="timestamp",
                team_id=team.pk,
                event=entity.id,
                parsed_date_from=(parsed_date_from or ""),
                parsed_date_to=(parsed_date_to or ""),
                filters="{filters}".format(filters=prop_filters) if filter.properties else "",
            )
        null_sql = NULL_SQL.format(
            interval=inteval_annotation,
            seconds_in_interval=seconds_in_interval,
            num_intervals=num_intervals,
            date_to=((filter.date_to or datetime.now())).strftime("%Y-%m-%d %H:%M:%S"),
        )

        final_query = AGGREGATE_SQL.format(null_sql=null_sql, content_sql=content_sql)

        try:
            result = ch_client.execute(final_query, params)

            parsed_results = self._parse_breakdown_response(result, filter, entity=entity)
        except:
            parsed_results = []

        return parsed_results

    def _calculate_trends(self, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        # format default dates

        if not filter._date_from:
            filter._date_from = relative_date_parse("-7d")
        if not filter._date_to:
            filter._date_to = datetime.now(timezone.utc)

        result = []
        for entity in filter.entities:
            if filter.compare:
                compare_filter = determine_compared_filter(filter=filter)
                entity_result = self._serialize_entity(entity, filter, team, "current")
                entity_result = convert_to_comparison(entity_result, filter, "{} - {}".format(entity.name, "current"))
                result.extend(entity_result)
                previous_entity_result = self._serialize_entity(entity, compare_filter, team, "previous")
                previous_entity_result = convert_to_comparison(
                    previous_entity_result, filter, "{} - {}".format(entity.name, "previous")
                )
                result.extend(previous_entity_result)
            else:
                entity_result = self._serialize_entity(entity, filter, team)
                result.extend(entity_result)

        return result

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self._calculate_trends(filter, team)

import copy
from datetime import timedelta
from itertools import accumulate
from typing import Any, Dict, List, Optional, Tuple, Union

from django.db.models.manager import BaseManager
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import get_interval_annotation_ch, get_time_diff, parse_timestamps
from ee.clickhouse.sql.events import (
    EVENT_JOIN_PERSON_SQL,
    EVENT_JOIN_PROPERTY_WITH_KEY_SQL,
    NULL_BREAKDOWN_SQL,
    NULL_SQL,
)
from ee.clickhouse.sql.trends.aggregate import AGGREGATE_SQL
from ee.clickhouse.sql.trends.breakdown import (
    BREAKDOWN_COHORT_FILTER_SQL,
    BREAKDOWN_COHORT_JOIN_SQL,
    BREAKDOWN_CONDITIONS_SQL,
    BREAKDOWN_DEFAULT_SQL,
    BREAKDOWN_PERSON_PROP_JOIN_SQL,
    BREAKDOWN_PROP_JOIN_SQL,
    BREAKDOWN_QUERY_SQL,
)
from ee.clickhouse.sql.trends.top_elements import TOP_ELEMENTS_ARRAY_OF_KEY_SQL
from ee.clickhouse.sql.trends.top_person_props import TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL
from ee.clickhouse.sql.trends.volume import VOLUME_ACTIONS_SQL, VOLUME_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TRENDS_CUMULATIVE
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery, convert_to_comparison, determine_compared_filter
from posthog.utils import relative_date_parse


class ClickhouseTrends(BaseQuery):
    def _calculate_trends(self, filter: Filter, team: Team) -> List[Dict[str, Any]]:

        # format default dates
        if not filter._date_from:
            filter._date_from = relative_date_parse("-7d")
        if not filter._date_to:
            filter._date_to = timezone.now()

        result = []
        for entity in filter.entities:
            if filter.compare:
                compare_filter = determine_compared_filter(filter=filter)
                entity_result = self._serialize_entity(entity, filter, team)
                entity_result = convert_to_comparison(entity_result, filter, "{} - {}".format(entity.name, "current"))
                result.extend(entity_result)
                previous_entity_result = self._serialize_entity(entity, compare_filter, team)
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

    def _serialize_entity(self, entity: Entity, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        if filter.breakdown:
            result = self._serialize_breakdown(entity, filter, team)
        else:
            result = self._format_normal_query(entity, filter, team)

        serialized_data = self._format_serialized(entity, result)

        if filter.display == TRENDS_CUMULATIVE:
            serialized_data = self._handle_cumulative(serialized_data)

        return serialized_data

    def _handle_cumulative(self, entity_metrics: List) -> List[Dict[str, Any]]:
        for metrics in entity_metrics:
            metrics.update(data=list(accumulate(metrics["data"])))
        return entity_metrics

    def _format_serialized(self, entity: Entity, result: List[Dict[str, Any]]):
        serialized_data = []

        serialized: Dict[str, Any] = {
            "action": entity.to_dict(),
            "label": entity.name,
            "count": 0,
            "data": [],
            "labels": [],
            "days": [],
        }

        for queried_metric in result:
            serialized_copy = copy.deepcopy(serialized)
            serialized_copy.update(queried_metric)
            serialized_data.append(serialized_copy)

        return serialized_data

    def _serialize_breakdown(self, entity: Entity, filter: Filter, team: Team):
        if isinstance(filter.breakdown, list) and "all" in filter.breakdown:
            result = []
            filter.breakdown = filter.breakdown if filter.breakdown and isinstance(filter.breakdown, list) else []
            filter.breakdown.remove("all")

            # handle breakdown by all and by specific props separately
            if filter.breakdown:
                result.extend(self._format_breakdown_query(entity, filter, team))

            filter.breakdown = ["all"]
            all_result = self._format_breakdown_query(entity, filter, team)

            result.extend(all_result)
        else:
            result = self._format_breakdown_query(entity, filter, team)
        return result

    def _format_breakdown_query(self, entity: Entity, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        params = {"team_id": team.pk}
        inteval_annotation = get_interval_annotation_ch(filter.interval)
        num_intervals, seconds_in_interval = get_time_diff(filter.interval or "day", filter.date_from, filter.date_to)
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)

        props_to_filter = [*filter.properties, *entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses("uuid", props_to_filter, team)

        aggregate_operation, join_condition, math_params = self._process_math(entity)

        action_query = ""
        action_params: Dict = {}
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, action_params = format_action_filter(action)

        null_sql = NULL_BREAKDOWN_SQL.format(
            interval=inteval_annotation,
            seconds_in_interval=seconds_in_interval,
            num_intervals=num_intervals,
            date_to=((filter.date_to or timezone.now()) + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"),
        )

        params = {**params, **math_params, **prop_filter_params}
        top_elements_array = []

        if filter.breakdown_type == "cohort":
            breakdown = filter.breakdown if filter.breakdown and isinstance(filter.breakdown, list) else []
            if "all" in breakdown:
                params = {**params, "event": entity.id, **action_params}
                null_sql = NULL_SQL.format(
                    interval=inteval_annotation,
                    seconds_in_interval=seconds_in_interval,
                    num_intervals=num_intervals,
                    date_to=((filter.date_to or timezone.now()) + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"),
                )
                conditions = BREAKDOWN_CONDITIONS_SQL.format(
                    parsed_date_from=parsed_date_from,
                    parsed_date_to=parsed_date_to,
                    actions_query="AND uuid IN ({})".format(action_query) if action_query else "",
                    event_filter="AND event = %(event)s" if not action_query else "",
                    filters="{filters}".format(filters=prop_filters) if props_to_filter else "",
                )
                breakdown_query = BREAKDOWN_DEFAULT_SQL.format(
                    null_sql=null_sql,
                    conditions=conditions,
                    event_join=join_condition,
                    aggregate_operation=aggregate_operation,
                )
            else:
                cohort_queries, cohort_ids, cohort_params = self._format_breakdown_cohort_join_query(breakdown, team)
                params = {**params, "values": cohort_ids, "event": entity.id, **action_params, **cohort_params}
                breakdown_filter = BREAKDOWN_COHORT_JOIN_SQL.format(
                    cohort_queries=cohort_queries,
                    parsed_date_from=parsed_date_from,
                    parsed_date_to=parsed_date_to,
                    actions_query="AND uuid IN ({})".format(action_query) if action_query else "",
                    event_filter="AND event = %(event)s" if not action_query else "",
                    filters="{filters}".format(filters=prop_filters) if props_to_filter else "",
                )
                breakdown_query = BREAKDOWN_QUERY_SQL.format(
                    null_sql=null_sql,
                    breakdown_filter=breakdown_filter,
                    event_join=join_condition,
                    aggregate_operation=aggregate_operation,
                )
        elif filter.breakdown_type == "person":
            top_elements_array = self._get_top_elements(
                TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL, filter, parsed_date_from, parsed_date_to, team
            )
            params = {
                **params,
                "values": top_elements_array,
                "key": filter.breakdown,
                "event": entity.id,
                **action_params,
            }
            breakdown_filter = BREAKDOWN_PERSON_PROP_JOIN_SQL.format(
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
                actions_query="AND uuid IN ({})".format(action_query) if action_query else "",
                event_filter="AND event = %(event)s" if not action_query else "",
            )
            breakdown_query = BREAKDOWN_QUERY_SQL.format(
                null_sql=null_sql,
                breakdown_filter=breakdown_filter,
                event_join=join_condition,
                aggregate_operation=aggregate_operation,
            )
        else:

            top_elements_array = self._get_top_elements(
                TOP_ELEMENTS_ARRAY_OF_KEY_SQL, filter, parsed_date_from, parsed_date_to, team
            )

            params = {
                **params,
                "values": top_elements_array,
                "key": filter.breakdown,
                "event": entity.id,
                **action_params,
            }
            breakdown_filter = BREAKDOWN_PROP_JOIN_SQL.format(
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
                actions_query="AND uuid IN ({})".format(action_query) if action_query else "",
                event_filter="AND event = %(event)s" if not action_query else "",
                filters="{filters}".format(filters=prop_filters) if props_to_filter else "",
            )
            breakdown_query = BREAKDOWN_QUERY_SQL.format(
                null_sql=null_sql,
                breakdown_filter=breakdown_filter,
                event_join=join_condition,
                aggregate_operation=aggregate_operation,
            )

        try:
            result = sync_execute(breakdown_query, params)
        except:
            result = []

        parsed_results = []

        for idx, stats in enumerate(result):

            breakdown_value = stats[2] if not filter.breakdown_type == "cohort" else ""
            stripped_value = breakdown_value.strip('"') if isinstance(breakdown_value, str) else breakdown_value

            extra_label = self._determine_breakdown_label(idx, filter.breakdown_type, filter.breakdown, stripped_value)
            label = "{} - {}".format(entity.name, extra_label)
            additional_values = {
                "label": label,
                "breakdown_value": filter.breakdown[idx]
                if isinstance(filter.breakdown, list)
                else filter.breakdown
                if filter.breakdown_type == "cohort"
                else stripped_value,
            }
            parsed_result = self._parse_response(stats, filter, additional_values)
            parsed_results.append(parsed_result)

        return parsed_results

    def _get_top_elements(
        self, query: str, filter: Filter, parsed_date_from: Optional[str], parsed_date_to: Optional[str], team: Team
    ) -> List:
        element_params = {"key": filter.breakdown, "limit": 20, "team_id": team.pk}
        element_query = query.format(parsed_date_from=parsed_date_from, parsed_date_to=parsed_date_to)

        try:
            top_elements_array_result = sync_execute(element_query, element_params)
            top_elements_array = top_elements_array_result[0][0]
        except:
            top_elements_array = []

        return top_elements_array

    def _format_breakdown_cohort_join_query(self, breakdown: List[Any], team: Team) -> Tuple[str, List, Dict]:
        cohorts = Cohort.objects.filter(team_id=team.pk, pk__in=[b for b in breakdown if b != "all"])
        cohort_queries, params = self._parse_breakdown_cohorts(cohorts)
        ids = [cohort.pk for cohort in cohorts]
        return cohort_queries, ids, params

    def _parse_breakdown_cohorts(self, cohorts: BaseManager) -> Tuple[str, Dict]:
        queries = []
        params: Dict[str, Any] = {}
        for cohort in cohorts:
            person_id_query, cohort_filter_params = format_filter_query(cohort)
            params = {**params, **cohort_filter_params}
            cohort_query = BREAKDOWN_COHORT_FILTER_SQL.format(clause=person_id_query, cohort_pk=cohort.pk)
            queries.append(cohort_query)
        return " UNION ALL ".join(queries), params

    def _parse_response(self, stats: Dict, filter: Filter, additional_values: Dict = {}) -> Dict[str, Any]:
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
        days = [
            ((item - timedelta(days=1)) if filter.interval == "month" else item).strftime(
                "%Y-%m-%d{}".format(" %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else "")
            )
            for item in stats[0]
        ]
        return {
            "data": counts,
            "count": sum(counts),
            "dates": dates,
            "labels": labels,
            "days": days,
            **additional_values,
        }

    def _determine_breakdown_label(
        self,
        index: int,
        breakdown_type: Optional[str],
        breakdown: Union[str, List[Union[str, int]], None],
        value: Union[str, int],
    ) -> str:
        breakdown = breakdown if breakdown and isinstance(breakdown, list) else []
        if breakdown_type == "cohort":
            if breakdown[index] == "all":
                return "all users"
            else:
                return Cohort.objects.get(pk=breakdown[index]).name
        else:
            return str(value) or ""

    def _process_math(self, entity):
        join_condition = ""
        aggregate_operation = "count(*)"
        params = {}
        if entity.math == "dau":
            join_condition = EVENT_JOIN_PERSON_SQL
            aggregate_operation = "count(DISTINCT person_id)"
        elif entity.math == "sum":
            aggregate_operation = "sum(value)"
            join_condition = EVENT_JOIN_PROPERTY_WITH_KEY_SQL
            params = {"join_property_key": entity.math_property}

        elif entity.math == "avg":
            aggregate_operation = "avg(value)"
            join_condition = EVENT_JOIN_PROPERTY_WITH_KEY_SQL
            params = {"join_property_key": entity.math_property}
        elif entity.math == "min":
            aggregate_operation = "min(value)"
            join_condition = EVENT_JOIN_PROPERTY_WITH_KEY_SQL
            params = {"join_property_key": entity.math_property}
        elif entity.math == "max":
            aggregate_operation = "max(value)"
            join_condition = EVENT_JOIN_PROPERTY_WITH_KEY_SQL
            params = {"join_property_key": entity.math_property}

        return aggregate_operation, join_condition, params

    def _format_normal_query(self, entity: Entity, filter: Filter, team: Team) -> List[Dict[str, Any]]:

        inteval_annotation = get_interval_annotation_ch(filter.interval)
        num_intervals, seconds_in_interval = get_time_diff(filter.interval or "day", filter.date_from, filter.date_to)
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)

        props_to_filter = [*filter.properties, *entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses("uuid", props_to_filter, team)

        aggregate_operation, join_condition, math_params = self._process_math(entity)

        params: Dict = {"team_id": team.pk}
        params = {**params, **prop_filter_params, **math_params}

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
                    filters="{filters}".format(filters=prop_filters) if props_to_filter else "",
                    event_join=join_condition,
                    aggregate_operation=aggregate_operation,
                )
            except:
                return []
        else:
            content_sql = VOLUME_SQL.format(
                interval=inteval_annotation,
                timestamp="timestamp",
                team_id=team.pk,
                parsed_date_from=(parsed_date_from or ""),
                parsed_date_to=(parsed_date_to or ""),
                filters="{filters}".format(filters=prop_filters) if props_to_filter else "",
                event_join=join_condition,
                aggregate_operation=aggregate_operation,
            )
            params = {**params, "event": entity.id}
        null_sql = NULL_SQL.format(
            interval=inteval_annotation,
            seconds_in_interval=seconds_in_interval,
            num_intervals=num_intervals,
            date_to=((filter.date_to or timezone.now())).strftime("%Y-%m-%d %H:%M:%S"),
        )

        final_query = AGGREGATE_SQL.format(null_sql=null_sql, content_sql=content_sql)

        try:
            result = sync_execute(final_query, params)

        except:
            result = []

        parsed_results = []
        for _, stats in enumerate(result):
            parsed_result = self._parse_response(stats, filter)
            parsed_results.append(parsed_result)

        return parsed_results

from typing import Any, Dict, List, Optional, Tuple, Union

from django.db.models.manager import BaseManager
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import parse_response, process_math
from ee.clickhouse.queries.util import get_interval_annotation_ch, get_time_diff, parse_timestamps
from ee.clickhouse.sql.events import NULL_BREAKDOWN_SQL, NULL_SQL
from ee.clickhouse.sql.person import GET_LATEST_PERSON_SQL
from ee.clickhouse.sql.trends.breakdown import (
    BREAKDOWN_COHORT_JOIN_SQL,
    BREAKDOWN_CONDITIONS_SQL,
    BREAKDOWN_DEFAULT_SQL,
    BREAKDOWN_PERSON_PROP_JOIN_SQL,
    BREAKDOWN_PROP_JOIN_SQL,
    BREAKDOWN_QUERY_SQL,
)
from ee.clickhouse.sql.trends.top_elements import TOP_ELEMENTS_ARRAY_OF_KEY_SQL
from ee.clickhouse.sql.trends.top_person_props import TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter


class ClickhouseTrendsBreakdown:
    def _serialize_breakdown(self, entity: Entity, filter: Filter, team_id: int):
        if isinstance(filter.breakdown, list) and "all" in filter.breakdown:
            result = []
            filter.breakdown = filter.breakdown if filter.breakdown and isinstance(filter.breakdown, list) else []
            filter.breakdown.remove("all")

            # handle breakdown by all and by specific props separately
            if filter.breakdown:
                result.extend(self._format_breakdown_query(entity, filter, team_id))

            filter.breakdown = ["all"]
            all_result = self._format_breakdown_query(entity, filter, team_id)

            result.extend(all_result)
        else:
            result = self._format_breakdown_query(entity, filter, team_id)
        return result

    def _format_breakdown_query(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:

        # process params
        params: Dict[str, Any] = {"team_id": team_id}
        interval_annotation = get_interval_annotation_ch(filter.interval)
        num_intervals, seconds_in_interval = get_time_diff(filter.interval or "day", filter.date_from, filter.date_to)
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)

        props_to_filter = [*filter.properties, *entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses(props_to_filter, team_id, table_name="e")
        aggregate_operation, join_condition, math_params = process_math(entity)

        action_query = ""
        action_params: Dict = {}
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, action_params = format_action_filter(action)

        null_sql = NULL_BREAKDOWN_SQL.format(
            interval=interval_annotation,
            seconds_in_interval=seconds_in_interval,
            num_intervals=num_intervals,
            date_to=(filter.date_to).strftime("%Y-%m-%d %H:%M:%S"),
        )

        params = {
            **params,
            **math_params,
            **prop_filter_params,
            **action_params,
            "event": entity.id,
            "key": filter.breakdown,
        }
        top_elements_array = []

        breakdown_filter_params = {
            "parsed_date_from": parsed_date_from,
            "parsed_date_to": parsed_date_to,
            "actions_query": "AND {}".format(action_query) if action_query else "",
            "event_filter": "AND event = %(event)s" if not action_query else "",
            "filters": prop_filters if props_to_filter else "",
        }

        if filter.breakdown_type == "cohort":
            breakdown = filter.breakdown if filter.breakdown and isinstance(filter.breakdown, list) else []
            if "all" in breakdown:
                null_sql = NULL_SQL
                breakdown_filter = BREAKDOWN_CONDITIONS_SQL
                breakdown_query = BREAKDOWN_DEFAULT_SQL
            else:
                cohort_queries, cohort_ids, cohort_params = self._format_breakdown_cohort_join_query(breakdown, team_id)
                params = {**params, "values": cohort_ids, **cohort_params}
                breakdown_filter = BREAKDOWN_COHORT_JOIN_SQL
                breakdown_filter_params = {**breakdown_filter_params, "cohort_queries": cohort_queries}
                breakdown_query = BREAKDOWN_QUERY_SQL
        elif filter.breakdown_type == "person":
            elements_query = TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL.format(
                parsed_date_from=parsed_date_from,
                parsed_date_to=parsed_date_to,
                latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
            )
            top_elements_array = self._get_top_elements(elements_query, filter, team_id)
            params = {
                **params,
                "values": top_elements_array,
            }
            breakdown_filter = BREAKDOWN_PERSON_PROP_JOIN_SQL
            breakdown_filter_params = {
                **breakdown_filter_params,
                "latest_person_sql": GET_LATEST_PERSON_SQL.format(query=""),
            }
            breakdown_query = BREAKDOWN_QUERY_SQL
        else:

            elements_query = TOP_ELEMENTS_ARRAY_OF_KEY_SQL.format(
                parsed_date_from=parsed_date_from, parsed_date_to=parsed_date_to
            )

            top_elements_array = self._get_top_elements(elements_query, filter, team_id)
            params = {
                **params,
                "values": top_elements_array,
            }
            breakdown_filter = BREAKDOWN_PROP_JOIN_SQL
            breakdown_query = BREAKDOWN_QUERY_SQL

        null_sql = null_sql.format(
            interval=interval_annotation,
            seconds_in_interval=seconds_in_interval,
            num_intervals=num_intervals,
            date_to=(filter.date_to).strftime("%Y-%m-%d %H:%M:%S"),
        )
        breakdown_filter = breakdown_filter.format(**breakdown_filter_params)
        breakdown_query = breakdown_query.format(
            null_sql=null_sql,
            breakdown_filter=breakdown_filter,
            event_join=join_condition,
            aggregate_operation=aggregate_operation,
            interval_annotation=interval_annotation,
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
            parsed_result = parse_response(stats, filter, additional_values)
            parsed_results.append(parsed_result)

        return parsed_results

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

    def _get_top_elements(self, query: str, filter: Filter, team_id: int) -> List:
        element_params = {"key": filter.breakdown, "limit": 20, "team_id": team_id}

        try:
            top_elements_array_result = sync_execute(query, element_params)
            top_elements_array = top_elements_array_result[0][0]
        except:
            top_elements_array = []

        return top_elements_array

    def _format_breakdown_cohort_join_query(self, breakdown: List[Any], team_id: int) -> Tuple[str, List, Dict]:
        cohorts = Cohort.objects.filter(team_id=team_id, pk__in=[b for b in breakdown if b != "all"])
        cohort_queries, params = self._parse_breakdown_cohorts(cohorts)
        ids = [cohort.pk for cohort in cohorts]
        return cohort_queries, ids, params

    def _parse_breakdown_cohorts(self, cohorts: BaseManager) -> Tuple[str, Dict]:
        queries = []
        params: Dict[str, Any] = {}
        for cohort in cohorts:
            person_id_query, cohort_filter_params = format_filter_query(cohort)
            params = {**params, **cohort_filter_params}
            cohort_query = person_id_query.replace(
                "SELECT distinct_id", "SELECT distinct_id, {} as value".format(cohort.pk)
            )
            queries.append(cohort_query)
        return " UNION ALL ".join(queries), params

from typing import Any, Dict, Iterable, List, Tuple, cast

from django.db.models.query import Prefetch

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.person import get_persons_by_uuids
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.retention.retention_event_query import RetentionEventsQuery
from ee.clickhouse.queries.util import get_trunc_func_ch
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from ee.clickhouse.sql.retention.people_in_period import (
    DEFAULT_REFERENCE_EVENT_PEOPLE_PER_PERIOD_SQL,
    DEFAULT_REFERENCE_EVENT_UNIQUE_PEOPLE_PER_PERIOD_SQL,
    REFERENCE_EVENT_PEOPLE_PER_PERIOD_SQL,
    REFERENCE_EVENT_UNIQUE_PEOPLE_PER_PERIOD_SQL,
    RETENTION_PEOPLE_PER_PERIOD_SQL,
)
from ee.clickhouse.sql.retention.retention import (
    INITIAL_INTERVAL_SQL,
    REFERENCE_EVENT_SQL,
    REFERENCE_EVENT_UNIQUE_SQL,
    RETENTION_PEOPLE_SQL,
    RETENTION_SQL,
)
from posthog.constants import (
    RETENTION_FIRST_TIME,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_LINEAR,
    RetentionQueryType,
)
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import RetentionFilter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.queries.retention import AppearanceRow, Retention


class ClickhouseRetention(Retention):
    def _execute_sql(self, filter: RetentionFilter, team: Team,) -> Dict[Tuple[int, int], Dict[str, Any]]:
        period = filter.period
        is_first_time_retention = filter.retention_type == RETENTION_FIRST_TIME
        date_from = filter.date_from
        trunc_func = get_trunc_func_ch(period)

        returning_event_query, returning_event_params = RetentionEventsQuery(
            filter=filter, team_id=team.pk, event_query_type=RetentionQueryType.RETURNING
        ).get_query()
        target_event_query, target_event_params = RetentionEventsQuery(
            filter=filter,
            team_id=team.pk,
            event_query_type=RetentionQueryType.TARGET_FIRST_TIME
            if is_first_time_retention
            else RetentionQueryType.TARGET,
        ).get_query()

        all_params = {
            "team_id": team.pk,
            "start_date": date_from.strftime(
                "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
            ),
            **returning_event_params,
            **target_event_params,
            "period": period,
        }

        result = sync_execute(
            RETENTION_SQL.format(
                returning_event_query=returning_event_query,
                trunc_func=trunc_func,
                target_event_query=target_event_query,
            ),
            all_params,
        )

        initial_interval_result = sync_execute(
            INITIAL_INTERVAL_SQL.format(reference_event_sql=target_event_query, trunc_func=trunc_func,), all_params
        )

        result_dict = {}
        for initial_res in initial_interval_result:
            result_dict.update({(initial_res[0], 0): {"count": initial_res[1], "people": []}})

        for res in result:
            result_dict.update({(res[0], res[1]): {"count": res[2], "people": []}})

        return result_dict

    def _get_condition(self, target_entity: Entity, table: str, prepend: str = "") -> Tuple[str, Dict]:
        if target_entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=target_entity.id)
            action_query, params = format_action_filter(action, prepend=prepend, use_loop=False)
            condition = action_query
        elif target_entity.type == TREND_FILTER_TYPE_EVENTS:
            condition = "{}.event = %({}_event)s".format(table, prepend)
            params = {"{}_event".format(prepend): target_entity.id}
        else:
            condition = "{}.event = %({}_event)s".format(table, prepend)
            params = {"{}_event".format(prepend): "$pageview"}
        return condition, params

    def _retrieve_people(self, filter: RetentionFilter, team: Team):
        period = filter.period
        is_first_time_retention = filter.retention_type == RETENTION_FIRST_TIME
        trunc_func = get_trunc_func_ch(period)
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)

        returning_entity = filter.returning_entity if filter.selected_interval > 0 else filter.target_entity
        target_query, target_params = self._get_condition(filter.target_entity, table="e")
        target_query_formatted = "AND {target_query}".format(target_query=target_query)
        return_query, return_params = self._get_condition(returning_entity, table="e", prepend="returning")
        return_query_formatted = "AND {return_query}".format(return_query=return_query)

        reference_event_query = (REFERENCE_EVENT_UNIQUE_SQL if is_first_time_retention else REFERENCE_EVENT_SQL).format(
            target_query=target_query_formatted,
            filters=prop_filters,
            trunc_func=trunc_func,
            GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
        )
        reference_date_from = filter.date_from
        reference_date_to = filter.date_from + filter.period_increment
        date_from = filter.date_from + filter.selected_interval * filter.period_increment
        date_to = date_from + filter.period_increment

        result = sync_execute(
            RETENTION_PEOPLE_SQL.format(
                reference_event_query=reference_event_query,
                target_query=return_query_formatted,
                filters=prop_filters,
                GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
            ),
            {
                "team_id": team.pk,
                "start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "end_date": date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "reference_start_date": reference_date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "reference_end_date": reference_date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "offset": filter.offset,
                **target_params,
                **return_params,
                **prop_filter_params,
            },
        )
        people = Person.objects.filter(team_id=team.pk, uuid__in=[val[0] for val in result])

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data

    def _retrieve_people_in_period(self, filter: RetentionFilter, team: Team):
        period = filter.period
        is_first_time_retention = filter.retention_type == RETENTION_FIRST_TIME
        trunc_func = get_trunc_func_ch(period)
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)

        target_query, target_params = self._get_condition(filter.target_entity, table="e")
        target_query_formatted = "AND {target_query}".format(target_query=target_query)
        return_query, return_params = self._get_condition(filter.returning_entity, table="e", prepend="returning")
        return_query_formatted = "AND {return_query}".format(return_query=return_query)

        first_event_sql = (
            REFERENCE_EVENT_UNIQUE_PEOPLE_PER_PERIOD_SQL
            if is_first_time_retention
            else REFERENCE_EVENT_PEOPLE_PER_PERIOD_SQL
        ).format(
            target_query=target_query_formatted,
            filters=prop_filters,
            trunc_func=trunc_func,
            GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
        )
        default_event_query = (
            DEFAULT_REFERENCE_EVENT_UNIQUE_PEOPLE_PER_PERIOD_SQL
            if is_first_time_retention
            else DEFAULT_REFERENCE_EVENT_PEOPLE_PER_PERIOD_SQL
        ).format(
            target_query=target_query_formatted,
            filters=prop_filters,
            trunc_func=trunc_func,
            GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
        )

        date_from = filter.date_from + filter.selected_interval * filter.period_increment
        date_to = filter.date_to

        filter = filter.with_data({"total_intervals": filter.total_intervals - filter.selected_interval})

        # NOTE: I'm using `Any` here to avoid typing issues when trying to iterate.
        query_result: Any = sync_execute(
            RETENTION_PEOPLE_PER_PERIOD_SQL.format(
                returning_query=return_query_formatted,
                filters=prop_filters,
                first_event_sql=first_event_sql,
                first_event_default_sql=default_event_query,
                trunc_func=trunc_func,
                GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
            ),
            {
                "team_id": team.pk,
                "start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "end_date": date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "offset": filter.offset,
                "limit": 100,
                "period": period,
                **target_params,
                **return_params,
                **prop_filter_params,
            },
        )

        people_appearances = [
            AppearanceRow(person_id=row[0], appearance_count=row[1], appearances=row[2]) for row in query_result
        ]

        from posthog.api.person import PersonSerializer

        people = get_persons_by_uuids(team_id=team.pk, uuids=[val[0] for val in query_result])
        people = people.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))

        people_dict = {str(person.uuid): PersonSerializer(person).data for person in people}

        result = self.process_people_in_period(
            filter=filter, people_appearances=people_appearances, people_dict=people_dict
        )
        return result

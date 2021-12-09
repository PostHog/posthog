from typing import Any, Dict, List, NamedTuple, Tuple, cast

from ee.clickhouse.client import substitute_params, sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.queries.person_distinct_id_query import get_team_distinct_ids_query
from ee.clickhouse.queries.retention.retention_actors import (
    ClickhouseRetentionActors,
    ClickhouseRetentionActorsByPeriod,
)
from ee.clickhouse.queries.retention.retention_event_query import RetentionEventsQuery
from ee.clickhouse.queries.util import get_trunc_func_ch
from ee.clickhouse.sql.retention.retention import (
    INITIAL_BREAKDOWN_INTERVAL_SQL,
    INITIAL_INTERVAL_SQL,
    RETENTION_BREAKDOWN_SQL,
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
from posthog.models.team import Team
from posthog.queries.retention import AppearanceRow, Retention

CohortKey = NamedTuple("CohortKey", (("breakdown_values", Tuple[str]), ("period", int)))


class ClickhouseRetention(Retention):
    def _get_retention_by_cohort(self, filter: RetentionFilter, team: Team,) -> Dict[Tuple[int, int], Dict[str, Any]]:
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
            INITIAL_INTERVAL_SQL.format(reference_event_sql=target_event_query, trunc_func=trunc_func,), all_params,
        )

        result_dict = {}
        for initial_res in initial_interval_result:
            result_dict.update({(initial_res[0], 0): {"count": initial_res[1], "people": []}})

        for res in result:
            result_dict.update({(res[0], res[1]): {"count": res[2], "people": []}})

        return result_dict

    def _get_retention_by_breakdown_values(
        self, filter: RetentionFilter, team: Team,
    ) -> Dict[CohortKey, Dict[str, Any]]:
        period = filter.period
        is_first_time_retention = filter.retention_type == RETENTION_FIRST_TIME
        date_from = filter.date_from
        trunc_func = get_trunc_func_ch(period)

        returning_event_query_templated, returning_event_params = RetentionEventsQuery(
            filter=filter.with_data({"breakdowns": []}),  # Avoid pulling in breakdown values from reterning event query
            team_id=team.pk,
            event_query_type=RetentionQueryType.RETURNING,
        ).get_query()

        returning_event_query = substitute_params(returning_event_query_templated, returning_event_params)

        target_event_query_templated, target_event_params = RetentionEventsQuery(
            filter=filter,
            team_id=team.pk,
            event_query_type=(
                RetentionQueryType.TARGET_FIRST_TIME if is_first_time_retention else RetentionQueryType.TARGET
            ),
        ).get_query()

        target_event_query = substitute_params(target_event_query_templated, target_event_params)

        all_params = {
            "team_id": team.pk,
            "start_date": date_from.strftime(
                "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
            ),
            "total_intervals": filter.total_intervals,
            "period": period.lower(),
            "breakdown_by": filter.breakdown,
        }

        result = sync_execute(
            substitute_params(RETENTION_BREAKDOWN_SQL, all_params).format(
                returning_event_query=returning_event_query,
                trunc_func=trunc_func,
                target_event_query=target_event_query,
                GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(team.pk),
            )
        )

        result = [(tuple(res[0]), *res[1:]) for res in result]  # make breakdown hashable, required later

        initial_interval_result = sync_execute(
            substitute_params(INITIAL_BREAKDOWN_INTERVAL_SQL, all_params).format(
                reference_event_sql=target_event_query, trunc_func=trunc_func,
            ),
        )

        initial_interval_result = [
            (tuple(res[0]), *res[1:]) for res in initial_interval_result
        ]  # make breakdown hashable, required later

        result_dict = {}
        for initial_res in initial_interval_result:
            result_dict.update({CohortKey(initial_res[0], 0): {"count": initial_res[1], "people": []}})

        for res in result:
            result_dict.update({CohortKey(res[0], res[1]): {"count": res[2], "people": []}})

        return result_dict

    def run(self, filter: RetentionFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        if filter.display == TRENDS_LINEAR:
            # If we get a display=TRENDS_LINEAR then don't do anything special
            # with breakdowns. This code path will be removed anyway in a future
            # change.
            retention_by_cohort = self._get_retention_by_cohort(filter, team)
            return self.process_graph_result(retention_by_cohort, filter)
        if filter.breakdowns and filter.breakdown_type:
            retention_by_breakdown = self._get_retention_by_breakdown_values(filter, team)
            return self.process_breakdown_table_result(retention_by_breakdown, filter)
        else:
            # If we're not using breakdowns, just use the non-clickhouse
            # `process_table_result`
            retention_by_cohort = self._get_retention_by_cohort(filter, team)
            return self.process_table_result(retention_by_cohort, filter)

    def process_breakdown_table_result(
        self, resultset: Dict[CohortKey, Dict[str, Any]], filter: RetentionFilter,
    ):
        result = [
            {
                "values": [
                    resultset.get(CohortKey(breakdown_values, interval), {"count": 0, "people": []})
                    for interval in range(filter.total_intervals)
                ],
                "label": "::".join(breakdown_values),
                "breakdown_values": breakdown_values,
            }
            for breakdown_values in set(
                cohort_key.breakdown_values for cohort_key in cast(Dict[CohortKey, Dict[str, Any]], resultset).keys()
            )
        ]

        return result

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

    def _retrieve_actors(self, filter: RetentionFilter, team: Team):
        _, serialized_actors = ClickhouseRetentionActors(filter=filter, team=team).get_actors()
        return serialized_actors

    def _retrieve_actors_in_period(self, filter: RetentionFilter, team: Team):
        query_builder = ClickhouseRetentionActorsByPeriod(filter=filter, team=team)
        query, params = query_builder.actor_query()

        # NOTE: I'm using `Any` here to avoid typing issues when trying to iterate.
        query_result: Any = sync_execute(query, params)

        actor_appearances = [
            AppearanceRow(actor_id=row[0], appearance_count=row[1], appearances=row[2]) for row in query_result
        ]

        _, serialized_actors = query_builder.get_actors_from_result(query_result)

        actor_dict = {str(actor["id"]): actor for actor in serialized_actors}

        # adjust total intervals to expected number of appearances based on selected interval
        filter = filter.with_data({"total_intervals": filter.total_intervals - filter.selected_interval})
        result = self.process_actors_in_period(
            filter=filter, actor_appearances=actor_appearances, actor_dict=actor_dict
        )

        return result

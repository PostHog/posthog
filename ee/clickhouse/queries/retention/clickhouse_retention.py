from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union
from urllib.parse import urlencode

from ee.clickhouse.queries.retention.retention_event_query import RetentionEventsQuery
from ee.clickhouse.sql.retention.retention import RETENTION_BREAKDOWN_SQL
from posthog.client import substitute_params, sync_execute
from posthog.constants import RETENTION_FIRST_TIME, RetentionQueryType
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.team import Team

BreakdownValues = Tuple[Union[str, int], ...]
CohortKey = NamedTuple("CohortKey", (("breakdown_values", BreakdownValues), ("period", int)))


class ClickhouseRetention:
    def __init__(self, base_uri="/"):
        self._base_uri = base_uri

    def run(self, filter: RetentionFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        retention_by_breakdown = self._get_retention_by_breakdown_values(filter, team)
        if filter.breakdowns:
            return self.process_breakdown_table_result(retention_by_breakdown, filter)
        else:
            return self.process_table_result(retention_by_breakdown, filter)

    def _get_retention_by_breakdown_values(
        self, filter: RetentionFilter, team: Team,
    ) -> Dict[CohortKey, Dict[str, Any]]:
        from ee.clickhouse.queries.retention.retention_actors import build_actor_activity_query

        actor_query = build_actor_activity_query(filter=filter, team=team)

        result = sync_execute(
            RETENTION_BREAKDOWN_SQL.format(actor_query=actor_query,),
            settings={"timeout_before_checking_execution_speed": 60},
        )

        result_dict = {
            CohortKey(tuple(breakdown_values), intervals_from_base): {
                "count": count,
                "people": [],
                "people_url": self._construct_people_url_for_trend_breakdown_interval(
                    filter=filter, breakdown_values=breakdown_values, selected_interval=intervals_from_base,
                ),
            }
            for (breakdown_values, intervals_from_base, count) in result
        }

        return result_dict

    def _construct_people_url_for_trend_breakdown_interval(
        self, filter: RetentionFilter, selected_interval: int, breakdown_values: BreakdownValues,
    ):
        params = RetentionFilter(
            {**filter._data, "breakdown_values": breakdown_values, "selected_interval": selected_interval}
        ).to_params()
        return f"{self._base_uri}api/person/retention/?{urlencode(params)}"

    def process_breakdown_table_result(
        self, resultset: Dict[CohortKey, Dict[str, Any]], filter: RetentionFilter,
    ):
        result = [
            {
                "values": [
                    resultset.get(CohortKey(breakdown_values, interval), {"count": 0, "people": []})
                    for interval in range(filter.total_intervals)
                ],
                "label": "::".join(map(str, breakdown_values)),
                "breakdown_values": breakdown_values,
                "people_url": (
                    "/api/person/retention/?"
                    f"{urlencode(RetentionFilter({**filter._data, 'display': 'ActionsTable', 'breakdown_values': breakdown_values}).to_params())}"
                ),
            }
            for breakdown_values in set(cohort_key.breakdown_values for cohort_key in resultset.keys())
        ]

        return result

    def process_table_result(
        self, resultset: Dict[CohortKey, Dict[str, Any]], filter: RetentionFilter,
    ):
        """
        Constructs a response for the rest api when there is no breakdown specified

        We process the non-breakdown case separately from the breakdown case so
        we can easily maintain compatability from when we didn't have
        breakdowns. The key difference is that we "zero fill" the cohorts as we
        want to have a result for each cohort between the specified date range.
        """

        def construct_url(first_day):
            params = RetentionFilter(
                {**filter._data, "display": "ActionsTable", "breakdown_values": [first_day]}
            ).to_params()
            return "/api/person/retention/?" f"{urlencode(params)}"

        result = [
            {
                "values": [
                    resultset.get(CohortKey((first_day,), day), {"count": 0, "people": []})
                    for day in range(filter.total_intervals - first_day)
                ],
                "label": "{} {}".format(filter.period, first_day),
                "date": (filter.date_from + RetentionFilter.determine_time_delta(first_day, filter.period)[0]),
                "people_url": construct_url(first_day),
            }
            for first_day in range(filter.total_intervals)
        ]

        return result

    def actors(self, filter: RetentionFilter, team: Team):
        from ee.clickhouse.queries.retention.retention_actors import ClickhouseRetentionActors

        _, serialized_actors = ClickhouseRetentionActors(team=team, filter=filter).get_actors()

        return serialized_actors

    def actors_in_period(self, filter: RetentionFilter, team: Team):
        """
        Creates a response of the form

        ```
        [
            {
                "person": {"distinct_id": ..., ...},
                "appearance_count": 3,
                "appearances": [1, 0, 1, 1, 0, 0]
            }
            ...
        ]
        ```

        where appearances values represent if the person was active in an
        interval, where the index of the list is the interval it refers to.
        """

        from ee.clickhouse.queries.retention.retention_actors import ClickhouseRetentionActorsByPeriod

        return ClickhouseRetentionActorsByPeriod(team=team, filter=filter).actors()


def build_returning_event_query(
    filter: RetentionFilter, team: Team, aggregate_users_by_distinct_id: Optional[bool] = None
):
    returning_event_query_templated, returning_event_params = RetentionEventsQuery(
        filter=filter.with_data({"breakdowns": []}),  # Avoid pulling in breakdown values from returning event query
        team=team,
        event_query_type=RetentionQueryType.RETURNING,
        aggregate_users_by_distinct_id=aggregate_users_by_distinct_id,
    ).get_query()

    query = substitute_params(returning_event_query_templated, returning_event_params)

    return query


def build_target_event_query(
    filter: RetentionFilter, team: Team, aggregate_users_by_distinct_id: Optional[bool] = None
):
    target_event_query_templated, target_event_params = RetentionEventsQuery(
        filter=filter,
        team=team,
        event_query_type=(
            RetentionQueryType.TARGET_FIRST_TIME
            if (filter.retention_type == RETENTION_FIRST_TIME)
            else RetentionQueryType.TARGET
        ),
        aggregate_users_by_distinct_id=aggregate_users_by_distinct_id,
    ).get_query()

    query = substitute_params(target_event_query_templated, target_event_params)

    return query

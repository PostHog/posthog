from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import pytz

from posthog.constants import RETENTION_FIRST_TIME, RetentionQueryType
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.team import Team
from posthog.queries.insight import insight_sync_execute
from posthog.queries.retention.actors_query import RetentionActorsByPeriod, build_actor_activity_query
from posthog.queries.retention.retention_events_query import RetentionEventsQuery
from posthog.queries.retention.sql import RETENTION_BREAKDOWN_SQL
from posthog.queries.retention.types import BreakdownValues, CohortKey
from posthog.queries.util import correct_result_for_sampling


class Retention:
    event_query = RetentionEventsQuery
    actors_by_period_query = RetentionActorsByPeriod

    def __init__(self, base_uri="/"):
        self._base_uri = base_uri

    def run(self, filter: RetentionFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        retention_by_breakdown = self._get_retention_by_breakdown_values(filter, team)
        if filter.breakdowns:
            return self.process_breakdown_table_result(retention_by_breakdown, filter)
        else:
            return self.process_table_result(retention_by_breakdown, filter, team)

    def _get_retention_by_breakdown_values(
        self, filter: RetentionFilter, team: Team
    ) -> Dict[CohortKey, Dict[str, Any]]:

        actor_query, actor_query_params = build_actor_activity_query(
            filter=filter, team=team, retention_events_query=self.event_query
        )
        result = insight_sync_execute(
            RETENTION_BREAKDOWN_SQL.format(actor_query=actor_query),
            {**actor_query_params, **filter.hogql_context.values},
            settings={"timeout_before_checking_execution_speed": 60},
            filter=filter,
            query_type="retention_by_breakdown_values",
        )

        result_dict = {
            CohortKey(tuple(breakdown_values), intervals_from_base): {
                "count": correct_result_for_sampling(count, filter.sampling_factor),
                "people": [],
                "people_url": self._construct_people_url_for_trend_breakdown_interval(
                    filter=filter, breakdown_values=breakdown_values, selected_interval=intervals_from_base
                ),
            }
            for (breakdown_values, intervals_from_base, count) in result
        }

        return result_dict

    def _construct_people_url_for_trend_breakdown_interval(
        self, filter: RetentionFilter, selected_interval: int, breakdown_values: BreakdownValues
    ):
        params = RetentionFilter(
            {**filter._data, "breakdown_values": breakdown_values, "selected_interval": selected_interval}
        ).to_params()
        return f"{self._base_uri}api/person/retention/?{urlencode(params)}"

    def process_breakdown_table_result(self, resultset: Dict[CohortKey, Dict[str, Any]], filter: RetentionFilter):
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

    def process_table_result(self, resultset: Dict[CohortKey, Dict[str, Any]], filter: RetentionFilter, team: Team):
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
                "date": (filter.date_from + RetentionFilter.determine_time_delta(first_day, filter.period)[0]).replace(
                    tzinfo=pytz.timezone(team.timezone)
                ),
                "people_url": construct_url(first_day),
            }
            for first_day in range(filter.total_intervals)
        ]

        return result

    def actors_in_period(self, filter: RetentionFilter, team: Team) -> Tuple[list, int]:
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

        return self.actors_by_period_query(team=team, filter=filter).actors()


def build_returning_event_query(
    filter: RetentionFilter,
    team: Team,
    aggregate_users_by_distinct_id: Optional[bool] = None,
    using_person_on_events: bool = False,
    retention_events_query=RetentionEventsQuery,
) -> Tuple[str, Dict[str, Any]]:
    returning_event_query_templated, returning_event_params = retention_events_query(
        filter=filter.shallow_clone({"breakdowns": []}),  # Avoid pulling in breakdown values from returning event query
        team=team,
        event_query_type=RetentionQueryType.RETURNING,
        aggregate_users_by_distinct_id=aggregate_users_by_distinct_id,
        using_person_on_events=using_person_on_events,
    ).get_query()

    return returning_event_query_templated, returning_event_params


def build_target_event_query(
    filter: RetentionFilter,
    team: Team,
    aggregate_users_by_distinct_id: Optional[bool] = None,
    using_person_on_events: bool = False,
    retention_events_query=RetentionEventsQuery,
) -> Tuple[str, Dict[str, Any]]:
    target_event_query_templated, target_event_params = retention_events_query(
        filter=filter,
        team=team,
        event_query_type=(
            RetentionQueryType.TARGET_FIRST_TIME
            if (filter.retention_type == RETENTION_FIRST_TIME)
            else RetentionQueryType.TARGET
        ),
        aggregate_users_by_distinct_id=aggregate_users_by_distinct_id,
        using_person_on_events=using_person_on_events,
    ).get_query()

    return target_event_query_templated, target_event_params

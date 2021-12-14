from typing import Any, Dict, List, Literal, NamedTuple, Optional, Tuple, cast

from urllib.parse import urlencode

from ee.clickhouse.queries.actor_base_query import get_actors_by_aggregation_by

from ee.clickhouse.client import substitute_params, sync_execute
from ee.clickhouse.models.person import get_persons_by_uuids
from ee.clickhouse.queries.retention.retention_event_query import RetentionEventsQuery
from ee.clickhouse.sql.retention.retention import (
    RETENTION_BREAKDOWN_ACTOR_SQL,
    RETENTION_BREAKDOWN_SQL,
)
from posthog.constants import (
    RETENTION_FIRST_TIME,
    RetentionQueryType,
)
from posthog.models.filters import RetentionFilter
from posthog.models.filters.retention_filter import RetentionPeopleRequest
from posthog.models.team import Team
from posthog.queries.retention import AppearanceRow, Retention, appearance_to_markers


CohortKey = NamedTuple("CohortKey", (("breakdown_values", Tuple[str]), ("period", int)))


class ClickhouseRetention(Retention):
    def run(self, filter: RetentionFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        retention_by_breakdown = self._get_retention_by_breakdown_values(filter, team)
        if filter.breakdowns:
            return self.process_breakdown_table_result(retention_by_breakdown, filter)
        else:
            return self.process_table_result(retention_by_breakdown, filter)

    def _get_retention_by_breakdown_values(
        self, filter: RetentionFilter, team: Team,
    ) -> Dict[CohortKey, Dict[str, Any]]:
        actor_query = build_actor_query(filter=filter, team=team)

        result = sync_execute(RETENTION_BREAKDOWN_SQL.format(actor_query=actor_query,))

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
        self, filter: RetentionFilter, selected_interval: int, breakdown_values: List[str],
    ):
        params = RetentionPeopleRequest(
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
                "label": "::".join(breakdown_values),
                "breakdown_values": breakdown_values,
                "people_url": (
                    "/api/person/retention/?"
                    f"{urlencode(RetentionPeopleRequest({**filter._data, 'display': 'ActionsTable', 'breakdown_values': breakdown_values}).to_params())}"
                ),
            }
            for breakdown_values in set(
                cohort_key.breakdown_values for cohort_key in cast(Dict[CohortKey, Dict[str, Any]], resultset).keys()
            )
        ]

        return result

    def process_table_result(
        self, resultset: Dict[Tuple[int, int], Dict[str, Any]], filter: RetentionFilter,
    ):
        """
        Constructs a response for the rest api when there is no breakdown specified

        We process the non-breakdown case separately from the breakdown case so
        we can easily maintain compatability from when we didn't have
        breakdowns. The key difference is that we "zero fill" the cohorts as we
        want to have a result for each cohort between the specified date range.
        """

        result = [
            {
                "values": [
                    resultset.get(((first_day,), day), {"count": 0, "people": []})
                    for day in range(filter.total_intervals - first_day)
                ],
                "label": "{} {}".format(filter.period, first_day),
                "date": (filter.date_from + RetentionFilter.determine_time_delta(first_day, filter.period)[0]),
                "people_url": (
                    "/api/person/retention/?"
                    f"{urlencode(RetentionPeopleRequest({**filter._data, 'display': 'ActionsTable', 'breakdown_values': [first_day]}).to_params())}"
                ),
            }
            for first_day in range(filter.total_intervals)
        ]

        return result

    def _retrieve_actors(self, filter: RetentionPeopleRequest, team: Team):
        actor_appearances = get_actor_appearances(
            filter=filter,
            # NOTE: If we don't have breakdown_values specified, and do not specify
            # breakdowns, then we need(?) to maintain backwards compatability with
            # non-breakdown functionality, which is to get the first cohort
            # values.
            filter_by_breakdown=filter.breakdown_values or [0],
            selected_interval=filter.selected_interval,
            team=team,
        )

        actors = get_actors_by_aggregation_by(
            team_id=team.pk,
            actor_type=filter.aggregation_group_type_index,
            actor_ids=[actor_appearance.actor_id for actor_appearance in actor_appearances],
        )

        return actors

    def _retrieve_actors_in_period(self, filter: RetentionPeopleRequest, team: Team):
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
        actor_appearances = get_actor_appearances(
            filter=filter,
            # NOTE: for backwards compat. if we don't have a breakdown value, we
            # use the `selected_interval` instead.
            filter_by_breakdown=filter.breakdown_values or [filter.selected_interval],
            team=team,
        )

        actors = get_actors_by_aggregation_by(
            team_id=team.pk,
            actor_type=filter.aggregation_group_type_index,
            actor_ids=[actor_appearance.actor_id for actor_appearance in actor_appearances],
        )

        actors_lookup = {actor["id"]: actor for actor in actors}

        print(actors_lookup)
        print(actor_appearances)

        return [
            {
                "person": actors_lookup.get(actor.actor_id, {"id": actor.actor_id, "distinct_ids": []}),
                "appearances": [
                    1 if interval_number in actor.appearances else 0
                    for interval_number in range(filter.total_intervals - (filter.selected_interval or 0))
                ],
            }
            for actor in sorted(actor_appearances, key=lambda x: x.actor_id)
        ]


def build_actor_query(
    filter: RetentionFilter,
    team: Team,
    filter_by_breakdown: Optional[List[str]] = None,
    selected_interval: Optional[int] = None,
) -> str:
    """
    The retention actor query is used to retrieve something of the form:

        breakdown_values, intervals_from_base, actor_id

    We use actor here as an abstraction over the different types we can have aside from
    person_ids
    """
    returning_event_query = build_returning_event_query(filter=filter, team=team)

    target_event_query = build_target_event_query(filter=filter, team=team)

    all_params = {
        "period": filter.period.lower(),
        "breakdown_values": list(filter_by_breakdown) if filter_by_breakdown else None,
        "selected_interval": selected_interval,
    }

    query = substitute_params(RETENTION_BREAKDOWN_ACTOR_SQL, all_params).format(
        returning_event_query=returning_event_query, target_event_query=target_event_query,
    )

    return query


def build_returning_event_query(filter: RetentionFilter, team: Team):
    returning_event_query_templated, returning_event_params = RetentionEventsQuery(
        filter=filter.with_data({"breakdowns": []}),  # Avoid pulling in breakdown values from returning event query
        team_id=team.pk,
        event_query_type=RetentionQueryType.RETURNING,
    ).get_query()

    query = substitute_params(returning_event_query_templated, returning_event_params)

    return query


def build_target_event_query(filter: RetentionFilter, team: Team):
    target_event_query_templated, target_event_params = RetentionEventsQuery(
        filter=filter,
        team_id=team.pk,
        event_query_type=(
            RetentionQueryType.TARGET_FIRST_TIME
            if (filter.retention_type == RETENTION_FIRST_TIME)
            else RetentionQueryType.TARGET
        ),
    ).get_query()

    query = substitute_params(target_event_query_templated, target_event_params)

    return query


def get_actor_appearances(
    filter: RetentionPeopleRequest,
    team: Team,
    filter_by_breakdown: Optional[List[str]] = None,
    selected_interval: Optional[int] = None,
) -> List[AppearanceRow]:
    """
    For a given filter request for Retention actor, return a list
    with one entry per person, and a list or `appearances` representing which periods
    they were active.
    """
    actor_activity_query = build_actor_query(
        filter=filter, team=team, filter_by_breakdown=filter_by_breakdown, selected_interval=selected_interval,
    )

    actor_query = f"""
        SELECT
            actor_id,
            groupArray(actor_activity.intervals_from_base) AS appearances

        FROM ({actor_activity_query}) AS actor_activity

        GROUP BY actor_id

        -- make sure we have stable ordering/pagination
        -- NOTE: relies on ids being monotonic
        ORDER BY actor_id

        LIMIT 100 OFFSET {filter.offset}
    """

    return [
        AppearanceRow(actor_id=str(row[0]), appearance_count=len(row[1]), appearances=row[1])
        for row in sync_execute(actor_query)
    ]

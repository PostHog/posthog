from dataclasses import dataclass
from itertools import groupby
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, cast

from urllib.parse import urlencode

from django.db.models.query import Prefetch

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
from posthog.queries.retention import AppearanceRow, Retention

CohortKey = NamedTuple("CohortKey", (("breakdown_values", Tuple[str]), ("period", int)))


class ClickhouseRetention(Retention):
    def run(self, filter: RetentionFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        retention_by_breakdown = self._get_retention_by_breakdown_values(filter, team)
        return self.process_breakdown_table_result(retention_by_breakdown, filter)

    def _get_retention_by_breakdown_values(
        self,
        filter: RetentionFilter,
        team: Team,
    ) -> Dict[CohortKey, Dict[str, Any]]:
        actor_query = build_actor_query(filter=filter, team=team)

        result = sync_execute(
            RETENTION_BREAKDOWN_SQL.format(
                actor_query=actor_query,
            )
        )

        result_dict = {
            CohortKey(tuple(breakdown_values), intervals_from_base): {
                "count": count,
                "people": [],
                "people_url": self._construct_people_url_for_trend_breakdown_interval(
                    filter=filter,
                    breakdown_values=breakdown_values,
                    selected_interval=intervals_from_base,
                ),
            }
            for (breakdown_values, intervals_from_base, count) in result
        }

        return result_dict

    def _construct_people_url_for_trend_breakdown_interval(
        self,
        filter: RetentionFilter,
        selected_interval: int,
        breakdown_values: List[str],
    ):
        params = RetentionPeopleRequest(
            {**filter._data, "breakdown_values": breakdown_values, "selected_interval": selected_interval}
        ).to_params()
        return f"{self._base_uri}api/person/retention/?{urlencode(params)}"

    def process_breakdown_table_result(
        self,
        resultset: Dict[CohortKey, Dict[str, Any]],
        filter: RetentionFilter,
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

    def _retrieve_people(self, filter: RetentionPeopleRequest, team: Team):
        people_appearances = get_people_appearances(filter=filter, team=team)
        people = get_persons_by_uuids(
            team_id=team.pk, uuids=[people_appearance.person_id for people_appearance in people_appearances]
        )

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data

    def _retrieve_people_in_period(self, filter: RetentionPeopleRequest, team: Team):
        people_appearances = get_people_appearances(filter=filter, team=team)
        people = get_persons_by_uuids(
            team_id=team.pk, uuids=[people_appearance.person_id for people_appearance in people_appearances]
        )

        people = people.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))

        from posthog.api.person import PersonSerializer

        people_dict = {str(person.uuid): PersonSerializer(person).data for person in people}

        result = self.process_people_in_period(
            filter=filter, people_appearances=people_appearances, people_dict=people_dict
        )
        return result


def build_actor_query(
    filter: RetentionFilter,
    team: Team,
    filter_by_breakdown: Optional[List[str]] = None,
    selected_interval: Optional[int] = None,
) -> str:
    """
    The retention actor query is used to retrieve something of the form:

        breakdown_values, intervals_from_base, person_id | cohort_id | organisation_id

    We use actor here as an abstraction over the different types we can have aside from
    person_ids
    """
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
            RetentionQueryType.TARGET_FIRST_TIME
            if (filter.retention_type == RETENTION_FIRST_TIME)
            else RetentionQueryType.TARGET
        ),
    ).get_query()

    target_event_query = substitute_params(target_event_query_templated, target_event_params)

    all_params = {
        "period": filter.period.lower(),
        "breakdown_values": list(filter_by_breakdown) if filter_by_breakdown else None,
        "selected_interval": selected_interval,
    }

    return substitute_params(RETENTION_BREAKDOWN_ACTOR_SQL, all_params).format(
        returning_event_query=returning_event_query,
        target_event_query=target_event_query,
    )


@dataclass
class ActorActivityRow:
    breakdown_values: List[str]
    intervals_from_base: int
    person_id: str


def get_people_appearances(filter: RetentionPeopleRequest, team: Team) -> List[AppearanceRow]:
    """
    For a given filter request for Retention people, return a list 
    with one entry per person, and a list or `appearances` representing which periods
    they were active.
    """
    person_activities = get_actor_activities(filter=filter, team=team)

    def build_appearance_row(person_id, person_activities):
        appearances = [person_activity.intervals_from_base for person_activity in person_activities]
        return AppearanceRow(
            person_id=person_id,
            appearance_count=len(appearances),
            appearances=appearances,
        )

    def sort_key(person_activity):
        return person_activity.person_id

    return [
        build_appearance_row(person_id=person_id, person_activities=person_activities)
        for (person_id, person_activities) in groupby(sorted(person_activities, key=sort_key), key=sort_key)
    ]


def get_actor_activities(filter: RetentionPeopleRequest, team: Team) -> List[ActorActivityRow]:
    actor_query = build_actor_query(
        filter=filter,
        team=team,
        filter_by_breakdown=filter.breakdown_values,
        selected_interval=filter.selected_interval,
    )
    return [
        ActorActivityRow(person_id=str(row[2]), breakdown_values=row[0], intervals_from_base=row[1])
        for row in sync_execute(actor_query)
    ]

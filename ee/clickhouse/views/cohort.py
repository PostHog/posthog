from typing import List

from django.db.models.query import QuerySet

from ee.clickhouse.queries.clickhouse_stickiness import retrieve_stickiness_people
from ee.clickhouse.queries.util import get_earliest_timestamp
from ee.clickhouse.views.actions import calculate_entity_people
from posthog.api.cohort import CohortSerializer, CohortViewSet
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team


class ClickhouseCohortSerializer(CohortSerializer):
    earliest_timestamp_func = lambda team_id: get_earliest_timestamp(team_id)

    def _fetch_stickiness_people(self, filter: StickinessFilter, team: Team) -> List[str]:
        serialized_people = retrieve_stickiness_people(filter, team)
        return [person["distinct_ids"][0] for person in serialized_people if len(person["distinct_ids"])]

    def _fetch_trend_people(self, filter: Filter, team: Team) -> List[str]:
        if len(filter.entities) >= 1:
            entity = filter.entities[0]
        else:
            entity = Entity({"id": filter.target_entity_id, "type": filter.target_entity_type})

        serialized_people = calculate_entity_people(team, entity, filter)
        return [person["distinct_ids"][0] for person in serialized_people if len(person["distinct_ids"])]


class ClickhouseCohortViewSet(CohortViewSet):
    serializer_class = ClickhouseCohortSerializer

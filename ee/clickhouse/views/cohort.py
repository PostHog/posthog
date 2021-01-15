from typing import List

from django.db.models.query import QuerySet

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.clickhouse_stickiness import insert_stickiness_people_into_cohort, retrieve_stickiness_people
from ee.clickhouse.queries.util import get_earliest_timestamp
from ee.clickhouse.sql.person import PERSON_STATIC_COHORT_TABLE
from ee.clickhouse.views.actions import calculate_entity_people, insert_entity_people_into_cohort
from posthog.api.cohort import CohortSerializer, CohortViewSet
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.tasks.calculate_cohort import insert_cohort_from_query


class ClickhouseCohortSerializer(CohortSerializer):
    earliest_timestamp_func = lambda team_id: get_earliest_timestamp(team_id)

    def _handle_stickiness_people(self, cohort: Cohort, filter: StickinessFilter, team: Team) -> None:
        insert_stickiness_people_into_cohort(cohort, filter, team)
        insert_cohort_from_query.delay(cohort.pk)

    def _handle_trend_people(self, cohort: Cohort, filter: Filter, team: Team) -> None:
        if len(filter.entities) >= 1:
            entity = filter.entities[0]
        else:
            entity = Entity({"id": filter.target_entity_id, "type": filter.target_entity_type})
        insert_entity_people_into_cohort(cohort, team, entity, filter)
        insert_cohort_from_query.delay(cohort.pk)


def insert_cohort_people_into_pg(cohort: Cohort):
    ids = sync_execute(
        "SELECT person_id FROM {} where cohort_id = %(cohort_id)s".format(PERSON_STATIC_COHORT_TABLE),
        {"cohort_id": cohort.pk},
    )
    cohort.insert_users_list_by_uuid(items=[str(id[0]) for id in ids])


class ClickhouseCohortViewSet(CohortViewSet):
    serializer_class = ClickhouseCohortSerializer

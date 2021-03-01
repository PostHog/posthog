from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.util import get_earliest_timestamp
from ee.clickhouse.sql.person import PERSON_STATIC_COHORT_TABLE
from posthog.api.cohort import CohortSerializer, CohortViewSet
from posthog.constants import INSIGHT_STICKINESS, INSIGHT_TRENDS
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.tasks.calculate_cohort import insert_cohort_from_query


class ClickhouseCohortSerializer(CohortSerializer):
    earliest_timestamp_func = get_earliest_timestamp

    def _handle_stickiness_people(self, target_entity: Entity, cohort: Cohort, filter: StickinessFilter) -> None:
        insert_cohort_from_query.delay(
            cohort.pk, INSIGHT_STICKINESS, filter.to_dict(), entity_data=target_entity.to_dict()
        )

    def _handle_trend_people(self, target_entity: Entity, cohort: Cohort, filter: Filter) -> None:
        insert_cohort_from_query.delay(cohort.pk, INSIGHT_TRENDS, filter.to_dict(), entity_data=target_entity.to_dict())


def insert_cohort_people_into_pg(cohort: Cohort):
    ids = sync_execute(
        "SELECT person_id FROM {} where team_id = %(team_id)s AND cohort_id = %(cohort_id)s".format(
            PERSON_STATIC_COHORT_TABLE
        ),
        {"cohort_id": cohort.pk, "team_id": cohort.team.pk},
    )
    cohort.insert_users_list_by_uuid(items=[str(id[0]) for id in ids])


class ClickhouseCohortViewSet(CohortViewSet):
    serializer_class = ClickhouseCohortSerializer

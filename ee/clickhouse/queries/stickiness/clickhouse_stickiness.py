from datetime import datetime
from typing import Any, Dict, Tuple

from django.conf import settings
from django.db.models.expressions import F
from django.utils import timezone
from rest_framework.request import Request
from sentry_sdk.api import capture_exception

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.person_distinct_id_query import get_team_distinct_ids_query
from ee.clickhouse.queries.stickiness.stickiness_actors import ClickhouseStickinessActors
from ee.clickhouse.queries.stickiness.stickiness_event_query import StickinessEventsQuery
from ee.clickhouse.sql.person import GET_LATEST_PERSON_SQL, INSERT_COHORT_ALL_PEOPLE_SQL, PERSON_STATIC_COHORT_TABLE
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.queries.stickiness import Stickiness


class ClickhouseStickiness(Stickiness):
    def stickiness(self, entity: Entity, filter: StickinessFilter, team_id: int) -> Dict[str, Any]:
        events_query, event_params = StickinessEventsQuery(entity, filter, team_id).get_query()

        query = f"""
        SELECT countDistinct(aggregation_target), num_intervals FROM ({events_query})
        WHERE num_intervals <= %(num_intervals)s
        GROUP BY num_intervals
        ORDER BY num_intervals
        """

        counts = sync_execute(query, {**event_params, "num_intervals": filter.total_intervals})
        return self.process_result(counts, filter, entity)

    def _retrieve_people(self, target_entity: Entity, filter: StickinessFilter, team: Team, request: Request):
        _, serialized_actors = ClickhouseStickinessActors(entity=target_entity, filter=filter, team=team).get_actors()
        return serialized_actors


def insert_stickiness_people_into_cohort(cohort: Cohort, target_entity: Entity, filter: StickinessFilter) -> None:
    content_sql, params = ClickhouseStickinessActors(
        entity=target_entity, filter=filter, team=cohort.team
    ).actor_query()

    try:
        sync_execute(
            INSERT_COHORT_ALL_PEOPLE_SQL.format(
                content_sql=content_sql,
                latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
                cohort_table=PERSON_STATIC_COHORT_TABLE,
                GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(cohort.team_id),
            ),
            {"cohort_id": cohort.pk, "_timestamp": datetime.now(), **params},
        )
        cohort.is_calculating = False
        cohort.last_calculation = timezone.now()
        cohort.errors_calculating = 0
        cohort.save()
    except Exception as err:
        if settings.DEBUG:
            raise err
        cohort.is_calculating = False
        cohort.errors_calculating = F("errors_calculating") + 1
        cohort.save()
        capture_exception(err)

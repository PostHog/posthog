from datetime import datetime
from typing import Dict

from django.conf import settings
from django.db.models.expressions import F
from django.utils import timezone
from rest_framework.request import Request
from sentry_sdk.api import capture_exception

from ee.clickhouse.client import substitute_params, sync_execute
from ee.clickhouse.queries.paths.paths_actors import ClickhousePathsActors
from ee.clickhouse.queries.stickiness.stickiness_actors import ClickhouseStickinessActors
from ee.clickhouse.queries.trends.person import ClickhouseTrendsActors
from ee.clickhouse.queries.util import get_earliest_timestamp
from ee.clickhouse.sql.person import INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID, PERSON_STATIC_COHORT_TABLE
from ee.clickhouse.views.person import get_funnel_actor_class
from posthog.api.cohort import CohortSerializer, CohortViewSet
from posthog.api.utils import get_target_entity
from posthog.constants import INSIGHT_FUNNELS, INSIGHT_PATHS, INSIGHT_STICKINESS, INSIGHT_TRENDS
from posthog.models.cohort import Cohort
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.tasks.calculate_cohort import insert_cohort_from_insight_filter


class ClickhouseCohortSerializer(CohortSerializer):
    earliest_timestamp_func = get_earliest_timestamp

    def _handle_static(self, cohort: Cohort, request: Request):
        if request.FILES.get("csv"):
            self._calculate_static_by_csv(request.FILES["csv"], cohort)
        else:
            filter_data = request.GET.dict()
            if filter_data:
                insert_cohort_from_insight_filter.delay(cohort.pk, filter_data)


def insert_cohort_people_into_pg(cohort: Cohort):
    ids = sync_execute(
        "SELECT person_id FROM {} where team_id = %(team_id)s AND cohort_id = %(cohort_id)s".format(
            PERSON_STATIC_COHORT_TABLE
        ),
        {"cohort_id": cohort.pk, "team_id": cohort.team.pk},
    )
    cohort.insert_users_list_by_uuid(items=[str(id[0]) for id in ids])


def insert_cohort_actors_into_ch(cohort: Cohort, filter_data: Dict):
    insight_type = filter_data.get("insight")

    if insight_type == INSIGHT_TRENDS:
        filter = Filter(data=filter_data)
        entity = get_target_entity(filter)
        query, params = ClickhouseTrendsActors(cohort.team, entity, filter).actor_query()
    elif insight_type == INSIGHT_STICKINESS:
        filter = StickinessFilter(data=filter_data, team=cohort.team)
        entity = get_target_entity(filter)
        query, params = ClickhouseStickinessActors(cohort.team, entity, filter).actor_query()
    elif insight_type == INSIGHT_FUNNELS:
        filter = Filter(data=filter_data)
        funnel_actor_class = get_funnel_actor_class(filter)
        query, params = funnel_actor_class(filter, cohort.team).actor_query()
    elif insight_type == INSIGHT_PATHS:
        filter = PathFilter(data=filter_data)
        query, params = ClickhousePathsActors(filter, cohort.team, funnel_filter=None).actor_query()

    insert_entity_people_into_cohort(cohort, substitute_params(query, params))


def insert_entity_people_into_cohort(cohort: Cohort, query: str):
    try:
        print(INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID.format(cohort_table=PERSON_STATIC_COHORT_TABLE, query=query))
        sync_execute(
            INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID.format(cohort_table=PERSON_STATIC_COHORT_TABLE, query=query),
            {"cohort_id": cohort.pk, "_timestamp": datetime.now(), "team_id": cohort.team.pk},
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


class ClickhouseCohortViewSet(CohortViewSet):
    serializer_class = ClickhouseCohortSerializer


class LegacyClickhouseCohortViewSet(ClickhouseCohortViewSet):
    legacy_team_compatibility = True

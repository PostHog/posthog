from django.db.models.query import QuerySet

from ee.clickhouse.queries.util import get_earliest_timestamp
from posthog.api.cohort import CohortSerializer, CohortViewSet
from posthog.models.filters.filter import Filter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team


class ClickhouseCohortSerializer(CohortSerializer):
    earliest_timestamp_func = lambda team_id: get_earliest_timestamp(team_id)

    def _fetch_stickiness_people(self, filter: StickinessFilter, team: Team) -> QuerySet:
        pass

    def _fetch_trend_people(self, filter: Filter, team: Team) -> QuerySet:
        pass


class ClickhouseCohortViewSet(CohortViewSet):
    serializer_class = ClickhouseCohortSerializer

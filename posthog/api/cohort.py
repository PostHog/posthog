import csv
from datetime import datetime
from typing import Any, Dict, List, Optional, cast

from django.conf import settings
from django.db.models import Count, QuerySet
from django.db.models.expressions import F
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from sentry_sdk.api import capture_exception

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.funnels.funnel_correlation_persons import FunnelCorrelationActors
from ee.clickhouse.queries.paths.paths_actors import ClickhousePathsActors
from ee.clickhouse.queries.stickiness.stickiness_actors import ClickhouseStickinessActors
from ee.clickhouse.queries.trends.person import ClickhouseTrendsActors
from ee.clickhouse.queries.util import get_earliest_timestamp
from ee.clickhouse.sql.person import INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID, PERSON_STATIC_COHORT_TABLE
from ee.clickhouse.views.person import get_funnel_actor_class
from posthog.api.action import calculate_people, filter_by_type
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_target_entity
from posthog.constants import INSIGHT_FUNNELS, INSIGHT_PATHS, INSIGHT_STICKINESS, INSIGHT_TRENDS, TRENDS_STICKINESS
from posthog.event_usage import report_user_action
from posthog.models import Cohort, Entity
from posthog.models.event import Event
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.user import User
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.stickiness import (
    stickiness_fetch_people,
    stickiness_format_intervals,
    stickiness_process_entity_type,
)
from posthog.tasks.calculate_cohort import (
    calculate_cohort_ch,
    calculate_cohort_from_list,
    insert_cohort_from_insight_filter,
)


class CohortSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    count = serializers.SerializerMethodField()
    earliest_timestamp_func = get_earliest_timestamp

    class Meta:
        model = Cohort
        fields = [
            "id",
            "name",
            "description",
            "groups",
            "deleted",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "errors_calculating",
            "count",
            "is_static",
        ]
        read_only_fields = [
            "id",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "errors_calculating",
            "count",
        ]

    def _handle_static(self, cohort: Cohort, request: Request):
        if request.FILES.get("csv"):
            self._calculate_static_by_csv(request.FILES["csv"], cohort)
        else:
            filter_data = request.GET.dict()
            if filter_data:
                insert_cohort_from_insight_filter.delay(cohort.pk, filter_data)

    def _handle_csv(self, file, cohort: Cohort) -> None:
        decoded_file = file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded_file)
        distinct_ids_and_emails = [row[0] for row in reader if len(row) > 0 and row]
        calculate_cohort_from_list.delay(cohort.pk, distinct_ids_and_emails)

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        if not validated_data.get("is_static"):
            validated_data["is_calculating"] = True
        cohort = Cohort.objects.create(team_id=self.context["team_id"], **validated_data)

        if cohort.is_static:
            self._handle_static(cohort, request)
        else:
            calculate_cohort_ch.delay(cohort.id)

        report_user_action(request.user, "cohort created", cohort.get_analytics_metadata())
        return cohort

    def _handle_static(self, cohort: Cohort, request: Request):
        if request.FILES.get("csv"):
            self._calculate_static_by_csv(request.FILES["csv"], cohort)
        else:
            try:
                filter = Filter(request=request)
                team = cast(User, request.user).team
                target_entity = get_target_entity(filter)
                if filter.shown_as == TRENDS_STICKINESS:
                    stickiness_filter = StickinessFilter(
                        request=request, team=team, get_earliest_timestamp=self.earliest_timestamp_func
                    )
                    self._handle_stickiness_people(target_entity, cohort, stickiness_filter)
                else:
                    self._handle_trend_people(target_entity, cohort, filter, request)
            except Exception as e:
                capture_exception(e)
                raise ValueError("This cohort has no conditions")

    def _calculate_static_by_csv(self, file, cohort: Cohort) -> None:
        decoded_file = file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded_file)
        distinct_ids_and_emails = [row[0] for row in reader if len(row) > 0 and row]
        calculate_cohort_from_list.delay(cohort.pk, distinct_ids_and_emails)

    def _calculate_static_by_people(self, people: List[str], cohort: Cohort) -> None:
        calculate_cohort_from_list.delay(cohort.pk, people)

    def _handle_stickiness_people(self, target_entity: Entity, cohort: Cohort, filter: StickinessFilter) -> None:
        events = stickiness_process_entity_type(target_entity, cohort.team, filter)
        events = stickiness_format_intervals(events, filter)
        people = stickiness_fetch_people(events, cohort.team, filter)
        ids = [person.distinct_ids[0] for person in people if len(person.distinct_ids)]
        self._calculate_static_by_people(ids, cohort)

    def _handle_trend_people(self, target_entity: Entity, cohort: Cohort, filter: Filter, request: Request) -> None:
        events = filter_by_type(entity=target_entity, team=cohort.team, filter=filter)
        people = calculate_people(team=cohort.team, events=events, filter=filter, request=request)
        ids = [person.distinct_ids[0] for person in people if len(person.distinct_ids)]
        self._calculate_static_by_people(ids, cohort)

    def update(self, cohort: Cohort, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
        request = self.context["request"]
        cohort.name = validated_data.get("name", cohort.name)
        cohort.description = validated_data.get("description", cohort.description)
        cohort.groups = validated_data.get("groups", cohort.groups)
        cohort.is_static = validated_data.get("is_static", cohort.is_static)
        deleted_state = validated_data.get("deleted", None)

        is_deletion_change = deleted_state is not None and cohort.deleted != deleted_state
        if is_deletion_change:
            cohort.deleted = deleted_state

        if not cohort.is_static and not is_deletion_change:
            cohort.is_calculating = True
        cohort.save()

        if not deleted_state:
            if cohort.is_static:
                # You can't update a static cohort using the trend/stickiness thing
                if request.FILES.get("csv"):
                    self._calculate_static_by_csv(request.FILES["csv"], cohort)
            else:
                calculate_cohort_ch.delay(cohort.id)

        report_user_action(
            request.user,
            "cohort updated",
            {**cohort.get_analytics_metadata(), "updated_by_creator": request.user == cohort.created_by},
        )

        return cohort

    def get_count(self, action: Cohort) -> Optional[int]:
        if hasattr(action, "count"):
            return action.count  # type: ignore
        return None


class CohortViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        queryset = queryset.annotate(count=Count("people"))
        return queryset.prefetch_related("created_by").order_by("-created_at")


class LegacyCohortViewSet(CohortViewSet):
    legacy_team_compatibility = True


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
    query_builder: ActorBaseQuery

    if insight_type == INSIGHT_TRENDS:
        filter = Filter(data=filter_data, team=cohort.team)
        entity = get_target_entity(filter)
        query_builder = ClickhouseTrendsActors(cohort.team, entity, filter)
    elif insight_type == INSIGHT_STICKINESS:
        stickiness_filter = StickinessFilter(data=filter_data, team=cohort.team)
        entity = get_target_entity(stickiness_filter)
        query_builder = ClickhouseStickinessActors(cohort.team, entity, stickiness_filter)
    elif insight_type == INSIGHT_FUNNELS:
        funnel_filter = Filter(data=filter_data, team=cohort.team)
        if funnel_filter.correlation_person_entity:
            query_builder = FunnelCorrelationActors(filter=funnel_filter, team=cohort.team)
        else:
            funnel_actor_class = get_funnel_actor_class(funnel_filter)
            query_builder = funnel_actor_class(filter=funnel_filter, team=cohort.team)
    elif insight_type == INSIGHT_PATHS:
        path_filter = PathFilter(data=filter_data, team=cohort.team)
        query_builder = ClickhousePathsActors(path_filter, cohort.team, funnel_filter=None)
    else:
        if settings.DEBUG:
            raise ValueError(f"Insight type: {insight_type} not supported for cohort creation")
        else:
            capture_exception(Exception(f"Insight type: {insight_type} not supported for cohort creation"))

    if query_builder.is_aggregating_by_groups:
        if settings.DEBUG:
            raise ValueError(f"Query type: Group based queries are not supported for cohort creation")
        else:
            capture_exception(Exception(f"Query type: Group based queries are not supported for cohort creation"))
    else:
        query, params = query_builder.actor_query(limit_actors=False)

    insert_actors_into_cohort_by_query(cohort, query, params)


def insert_actors_into_cohort_by_query(cohort: Cohort, query: str, params: Dict[str, Any]):
    try:
        sync_execute(
            INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID.format(cohort_table=PERSON_STATIC_COHORT_TABLE, query=query),
            {"cohort_id": cohort.pk, "_timestamp": datetime.now(), "team_id": cohort.team.pk, **params},
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

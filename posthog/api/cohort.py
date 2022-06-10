import csv
from datetime import datetime
from typing import Any, Dict

from django.conf import settings
from django.db.models import QuerySet
from django.db.models.expressions import F
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers
from sentry_sdk.api import capture_exception

from ee.clickhouse.queries.funnels.funnel_correlation_persons import FunnelCorrelationActors
from ee.clickhouse.queries.paths import ClickhousePathsActors
from ee.clickhouse.queries.stickiness.stickiness_actors import ClickhouseStickinessActors
from ee.clickhouse.sql.person import INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID, PERSON_STATIC_COHORT_TABLE
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.person import get_funnel_actor_class, should_paginate
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_target_entity
from posthog.client import sync_execute
from posthog.constants import (
    CSV_EXPORT_LIMIT,
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    INSIGHT_STICKINESS,
    INSIGHT_TRENDS,
    LIMIT,
    OFFSET,
)
from posthog.event_usage import report_user_action
from posthog.models import Cohort
from posthog.models.cohort import get_and_update_pending_version
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.actor_base_query import ActorBaseQuery, get_people
from posthog.queries.person_query import PersonQuery
from posthog.queries.trends.person import TrendsActors
from posthog.queries.util import get_earliest_timestamp
from posthog.tasks.calculate_cohort import (
    calculate_cohort_ch,
    calculate_cohort_from_list,
    insert_cohort_from_insight_filter,
)
from posthog.utils import format_query_params_absolute_url


class CohortSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    earliest_timestamp_func = get_earliest_timestamp

    class Meta:
        model = Cohort
        fields = [
            "id",
            "name",
            "description",
            "groups",
            "deleted",
            "filters",
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
        team: Team = Team.objects.get(pk=self.context["team_id"])
        validated_data["created_by"] = request.user

        if not validated_data.get("is_static"):
            validated_data["is_calculating"] = True
        cohort = Cohort.objects.create(team_id=self.context["team_id"], **validated_data)

        if cohort.is_static:
            self._handle_static(cohort, request)
        else:
            pending_version = get_and_update_pending_version(cohort)

            calculate_cohort_ch.delay(cohort.id, pending_version)

        report_user_action(request.user, "cohort created", cohort.get_analytics_metadata())
        return cohort

    def _calculate_static_by_csv(self, file, cohort: Cohort) -> None:
        decoded_file = file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded_file)
        distinct_ids_and_emails = [row[0] for row in reader if len(row) > 0 and row]
        calculate_cohort_from_list.delay(cohort.pk, distinct_ids_and_emails)

    def validate_filters(self, request_filters: Dict):

        if isinstance(request_filters, dict) and "properties" in request_filters:
            return request_filters
        else:
            raise ValidationError("Filters must be a dictionary with a 'properties' key.")

    def update(self, cohort: Cohort, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
        request = self.context["request"]

        cohort.name = validated_data.get("name", cohort.name)
        cohort.description = validated_data.get("description", cohort.description)
        cohort.groups = validated_data.get("groups", cohort.groups)
        cohort.is_static = validated_data.get("is_static", cohort.is_static)
        cohort.filters = validated_data.get("filters", cohort.filters)
        deleted_state = validated_data.get("deleted", None)

        is_deletion_change = deleted_state is not None and cohort.deleted != deleted_state
        if is_deletion_change:
            cohort.deleted = deleted_state

        if not cohort.is_static and not is_deletion_change:
            cohort.is_calculating = True

        if will_create_loops(cohort):
            raise ValidationError("Cohorts cannot reference other cohorts in a loop.")

        cohort.save()

        if not deleted_state:
            if cohort.is_static:
                # You can't update a static cohort using the trend/stickiness thing
                if request.FILES.get("csv"):
                    self._calculate_static_by_csv(request.FILES["csv"], cohort)
            else:
                # Increment based on pending versions
                pending_version = get_and_update_pending_version(cohort)

                calculate_cohort_ch.delay(cohort.id, pending_version)

        report_user_action(
            request.user,
            "cohort updated",
            {**cohort.get_analytics_metadata(), "updated_by_creator": request.user == cohort.created_by},
        )

        return cohort

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["filters"] = (
            instance.filters if instance.filters else {"properties": instance.properties.to_dict()}
        )
        return representation


class CohortViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        return queryset.prefetch_related("created_by").order_by("-created_at")

    @action(
        methods=["GET"],
        detail=True,
        renderer_classes=[*api_settings.DEFAULT_RENDERER_CLASSES, csvrenderers.PaginatedCSVRenderer],
    )
    def persons(self, request: Request, **kwargs) -> Response:
        cohort: Cohort = self.get_object()
        team = self.team
        filter = Filter(request=request, team=self.team)

        is_csv_request = self.request.accepted_renderer.format == "csv"
        if is_csv_request:
            filter = filter.with_data({LIMIT: CSV_EXPORT_LIMIT, OFFSET: 0})
        elif not filter.limit:
            filter = filter.with_data({LIMIT: 100})

        query, params = PersonQuery(filter, team.pk, cohort=cohort).get_query()

        raw_result = sync_execute(query, params)
        actor_ids = [row[0] for row in raw_result]
        actors, serialized_actors = get_people(team.pk, actor_ids)

        _should_paginate = should_paginate(actors, filter.limit)
        next_url = format_query_params_absolute_url(request, filter.offset + filter.limit) if _should_paginate else None
        previous_url = (
            format_query_params_absolute_url(request, filter.offset - filter.limit)
            if filter.offset - filter.limit >= 0
            else None
        )

        return Response({"results": serialized_actors, "next": next_url, "previous": previous_url})


class LegacyCohortViewSet(CohortViewSet):
    legacy_team_compatibility = True


def will_create_loops(cohort: Cohort) -> bool:
    # Loops can only be formed when trying to update a Cohort, not when creating one
    team_id = cohort.team_id
    cohorts_seen = set([cohort.pk])
    cohorts_queue = [property.value for property in cohort.properties.flat if property.type == "cohort"]
    while cohorts_queue:
        current_cohort_id = cohorts_queue.pop()

        if current_cohort_id in cohorts_seen:
            return True

        cohorts_seen.add(current_cohort_id)

        try:
            current_cohort: Cohort = Cohort.objects.get(pk=current_cohort_id, team_id=team_id)
        except Cohort.DoesNotExist:
            raise ValidationError("Invalid Cohort ID in filter")

        properties = current_cohort.properties.flat
        for property in properties:
            if property.type == "cohort":
                if property.value in cohorts_seen:
                    return True
                else:
                    cohorts_queue.append(property.value)

    return False


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
        query_builder = TrendsActors(cohort.team, entity, filter)
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
        cohort.save(update_fields=["errors_calculating", "last_calculation", "is_calculating"])
    except Exception as err:

        if settings.DEBUG:
            raise err
        cohort.is_calculating = False
        cohort.errors_calculating = F("errors_calculating") + 1
        cohort.save(update_fields=["errors_calculating", "is_calculating"])
        capture_exception(err)

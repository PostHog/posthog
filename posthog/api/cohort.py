import csv
import json
from posthog.queries.insight import insight_sync_execute
import posthoganalytics
from posthog.metrics import LABEL_TEAM_ID
from posthog.renderers import SafeJSONRenderer
from datetime import datetime
from typing import Any, Dict, cast

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

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.person import get_funnel_actor_class
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_target_entity
from posthog.client import sync_execute
from posthog.constants import (
    CSV_EXPORT_LIMIT,
    INSIGHT_FUNNELS,
    INSIGHT_LIFECYCLE,
    INSIGHT_PATHS,
    INSIGHT_STICKINESS,
    INSIGHT_TRENDS,
    LIMIT,
    OFFSET,
)
from posthog.event_usage import report_user_action
from posthog.hogql.context import HogQLContext
from posthog.models import Cohort, FeatureFlag, User, Person
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.cohort.util import get_dependent_cohorts
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.lifecycle_filter import LifecycleFilter
from posthog.models.person.sql import (
    INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID,
    PERSON_STATIC_COHORT_TABLE,
)
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.queries.actor_base_query import (
    ActorBaseQuery,
    get_people,
    serialize_people,
)
from posthog.queries.paths import PathsActors
from posthog.queries.person_query import PersonQuery
from posthog.queries.stickiness import StickinessActors
from posthog.queries.trends.trends_actors import TrendsActors
from posthog.queries.trends.lifecycle_actors import LifecycleActors
from posthog.queries.util import get_earliest_timestamp
from posthog.tasks.calculate_cohort import (
    calculate_cohort_from_list,
    insert_cohort_from_insight_filter,
    update_cohort,
)
from posthog.utils import format_query_params_absolute_url
from prometheus_client import Counter


API_COHORT_PERSON_BYTES_READ_FROM_POSTGRES_COUNTER = Counter(
    "api_cohort_person_bytes_read_from_postgres",
    "An estimate of how many bytes we've read from postgres to service person cohort endpoint.",
    labelnames=[LABEL_TEAM_ID],
)


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

    def _handle_static(self, cohort: Cohort, context: Dict) -> None:
        request = self.context["request"]
        if request.FILES.get("csv"):
            self._calculate_static_by_csv(request.FILES["csv"], cohort)
        else:
            filter_data = request.GET.dict()
            existing_cohort_id = context.get("from_cohort_id")
            if existing_cohort_id:
                filter_data = {**filter_data, "from_cohort_id": existing_cohort_id}
            if filter_data:
                insert_cohort_from_insight_filter.delay(cohort.pk, filter_data)

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context["request"]
        validated_data["created_by"] = request.user

        if not validated_data.get("is_static"):
            validated_data["is_calculating"] = True
        cohort = Cohort.objects.create(team_id=self.context["team_id"], **validated_data)

        if cohort.is_static:
            self._handle_static(cohort, self.context)
        else:
            update_cohort(cohort)

        report_user_action(request.user, "cohort created", cohort.get_analytics_metadata())
        return cohort

    def _calculate_static_by_csv(self, file, cohort: Cohort) -> None:
        decoded_file = file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded_file)
        distinct_ids_and_emails = [row[0] for row in reader if len(row) > 0 and row]
        calculate_cohort_from_list.delay(cohort.pk, distinct_ids_and_emails)

    def validate_filters(self, request_filters: Dict):
        if isinstance(request_filters, dict) and "properties" in request_filters:
            if self.context["request"].method == "PATCH":
                parsed_filter = Filter(data=request_filters)
                instance = cast(Cohort, self.instance)
                cohort_id = instance.pk
                flags: QuerySet[FeatureFlag] = FeatureFlag.objects.filter(
                    team_id=self.context["team_id"], active=True, deleted=False
                )
                cohort_used_in_flags = len([flag for flag in flags if cohort_id in flag.get_cohort_ids()]) > 0

                for prop in parsed_filter.property_groups.flat:
                    if prop.type == "behavioral":
                        if cohort_used_in_flags:
                            raise serializers.ValidationError(
                                detail=f"Behavioral filters cannot be added to cohorts used in feature flags.",
                                code="behavioral_cohort_found",
                            )

                    if prop.type == "cohort":
                        nested_cohort = Cohort.objects.get(pk=prop.value)
                        dependent_cohorts = get_dependent_cohorts(nested_cohort)
                        for dependent_cohort in [nested_cohort, *dependent_cohorts]:
                            if (
                                cohort_used_in_flags
                                and len(
                                    [prop for prop in dependent_cohort.properties.flat if prop.type == "behavioral"]
                                )
                                > 0
                            ):
                                raise serializers.ValidationError(
                                    detail=f"A dependent cohort ({dependent_cohort.name}) has filters based on events. These cohorts can't be used in feature flags.",
                                    code="behavioral_cohort_found",
                                )

            return request_filters
        else:
            raise ValidationError("Filters must be a dictionary with a 'properties' key.")

    def update(self, cohort: Cohort, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
        request = self.context["request"]
        user = cast(User, request.user)

        cohort.name = validated_data.get("name", cohort.name)
        cohort.description = validated_data.get("description", cohort.description)
        cohort.groups = validated_data.get("groups", cohort.groups)
        cohort.is_static = validated_data.get("is_static", cohort.is_static)
        cohort.filters = validated_data.get("filters", cohort.filters)
        deleted_state = validated_data.get("deleted", None)

        is_deletion_change = deleted_state is not None and cohort.deleted != deleted_state
        if is_deletion_change:
            cohort.deleted = deleted_state
            if deleted_state:
                AsyncDeletion.objects.get_or_create(
                    deletion_type=DeletionType.Cohort_full,
                    team_id=cohort.team.pk,
                    key=f"{cohort.pk}_{cohort.version}",
                    created_by=user,
                )
            else:
                AsyncDeletion.objects.filter(
                    deletion_type=DeletionType.Cohort_full,
                    team_id=cohort.team.pk,
                    key=f"{cohort.pk}_{cohort.version}",
                ).delete()
        elif not cohort.is_static:
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
                update_cohort(cohort)

        report_user_action(
            request.user,
            "cohort updated",
            {
                **cohort.get_analytics_metadata(),
                "updated_by_creator": request.user == cohort.created_by,
            },
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
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        return queryset.prefetch_related("created_by", "team").order_by("-created_at")

    @action(
        methods=["GET"],
        detail=True,
    )
    def duplicate_as_static_cohort(self, request: Request, **kwargs) -> Response:
        cohort: Cohort = self.get_object()
        team = self.team

        if cohort.is_static:
            raise ValidationError("Cannot duplicate a static cohort as a static cohort.")

        cohort_serializer = CohortSerializer(
            data={
                "name": f"{cohort.name} (static copy)",
                "is_static": True,
            },
            context={
                "request": request,
                "from_cohort_id": cohort.pk,
                "team_id": team.pk,
            },
        )

        cohort_serializer.is_valid(raise_exception=True)
        cohort_serializer.save()

        return Response(cohort_serializer.data)

    @action(
        methods=["GET"],
        detail=True,
        renderer_classes=[
            *api_settings.DEFAULT_RENDERER_CLASSES,
            csvrenderers.PaginatedCSVRenderer,
        ],
    )
    def persons(self, request: Request, **kwargs) -> Response:
        cohort: Cohort = self.get_object()
        team = self.team
        filter = Filter(request=request, team=self.team)
        assert request.user.is_authenticated

        is_csv_request = self.request.accepted_renderer.format == "csv" or request.GET.get("is_csv_export")
        if is_csv_request and not filter.limit:
            filter = filter.shallow_clone({LIMIT: CSV_EXPORT_LIMIT, OFFSET: 0})
        elif not filter.limit:
            filter = filter.shallow_clone({LIMIT: 100})

        if posthoganalytics.feature_enabled(
            "load-person-fields-from-clickhouse",
            request.user.distinct_id,
            person_properties={"email": request.user.email},
        ):
            person_query = PersonQuery(
                filter,
                team.pk,
                cohort=cohort,
                extra_fields=[
                    "created_at",
                    "properties",
                    "is_identified",
                ],
                include_distinct_ids=True,
            )
            paginated_query, paginated_params = person_query.get_query(paginate=True, filter_future_persons=True)
            serialized_actors = insight_sync_execute(
                paginated_query,
                {**paginated_params, **filter.hogql_context.values},
                filter=filter,
                query_type="cohort_persons",
                team_id=team.pk,
            )
            persons = []
            for p in serialized_actors:
                person = Person(
                    uuid=p[0],
                    created_at=p[1],
                    is_identified=p[2],
                    properties=json.loads(p[3]),
                )
                person._distinct_ids = p[4]
                persons.append(person)

            serialized_actors = serialize_people(team, data=persons)
            _should_paginate = len(serialized_actors) >= filter.limit
        else:
            query, params = PersonQuery(filter, team.pk, cohort=cohort).get_query(paginate=True)
            raw_result = sync_execute(query, {**params, **filter.hogql_context.values})
            actor_ids = [row[0] for row in raw_result]
            actors, serialized_actors = get_people(team, actor_ids, distinct_id_limit=10)

            _should_paginate = len(actor_ids) >= filter.limit

        next_url = format_query_params_absolute_url(request, filter.offset + filter.limit) if _should_paginate else None
        previous_url = (
            format_query_params_absolute_url(request, filter.offset - filter.limit)
            if filter.offset - filter.limit >= 0
            else None
        )
        if is_csv_request:
            KEYS_ORDER = [
                "id",
                "email",
                "name",
                "created_at",
                "properties",
                "distinct_ids",
            ]
            DELETE_KEYS = [
                "value_at_data_point",
                "uuid",
                "type",
                "is_identified",
                "matched_recordings",
            ]
            for actor in serialized_actors:
                if actor["properties"].get("email"):
                    actor["email"] = actor["properties"]["email"]
                    del actor["properties"]["email"]
            serialized_actors = [
                {
                    k: v
                    for k, v in sorted(
                        actor.items(),
                        key=lambda item: KEYS_ORDER.index(item[0]) if item[0] in KEYS_ORDER else 999999,
                    )
                    if k not in DELETE_KEYS
                }
                for actor in serialized_actors
            ]

        # TEMPORARY: Work out usage patterns of this endpoint
        renderer = SafeJSONRenderer()
        size = len(renderer.render(serialized_actors))
        API_COHORT_PERSON_BYTES_READ_FROM_POSTGRES_COUNTER.labels(team_id=team.pk).inc(size)

        return Response({"results": serialized_actors, "next": next_url, "previous": previous_url})


class LegacyCohortViewSet(CohortViewSet):
    legacy_team_compatibility = True


def will_create_loops(cohort: Cohort) -> bool:
    # Loops can only be formed when trying to update a Cohort, not when creating one
    team_id = cohort.team_id

    # We can model this as a directed graph, where each node is a Cohort and each edge is a reference to another Cohort
    # There's a loop only if there's a cycle in the directed graph. The "directed" bit is important.
    # For example, if Cohort A exists, and Cohort B references Cohort A, and Cohort C references both Cohort A & B
    # then, there's no cycle, because we can compute cohort A, using which we can compute cohort B, using which we can compute cohort C.

    # However, if cohort A depended on Cohort C, then we'd have a cycle, because we can't compute Cohort A without computing Cohort C, and on & on.

    # For a good explainer of this algorithm, see: https://www.geeksforgeeks.org/detect-cycle-in-a-graph/

    def dfs_loop_helper(current_cohort: Cohort, seen_cohorts, cohorts_on_path):
        seen_cohorts.add(current_cohort.pk)
        cohorts_on_path.add(current_cohort.pk)

        for property in current_cohort.properties.flat:
            if property.type == "cohort":
                if property.value in cohorts_on_path:
                    return True
                elif property.value not in seen_cohorts:
                    try:
                        nested_cohort = Cohort.objects.get(pk=property.value, team_id=team_id)
                    except Cohort.DoesNotExist:
                        raise ValidationError("Invalid Cohort ID in filter")

                    if dfs_loop_helper(nested_cohort, seen_cohorts, cohorts_on_path):
                        return True

        cohorts_on_path.remove(current_cohort.pk)
        return False

    return dfs_loop_helper(cohort, set(), set())


def insert_cohort_people_into_pg(cohort: Cohort):
    ids = sync_execute(
        "SELECT person_id FROM {} where team_id = %(team_id)s AND cohort_id = %(cohort_id)s".format(
            PERSON_STATIC_COHORT_TABLE
        ),
        {"cohort_id": cohort.pk, "team_id": cohort.team.pk},
    )
    cohort.insert_users_list_by_uuid(items=[str(id[0]) for id in ids])


def insert_cohort_actors_into_ch(cohort: Cohort, filter_data: Dict):
    from_existing_cohort_id = filter_data.get("from_cohort_id")
    context: HogQLContext

    if from_existing_cohort_id:
        existing_cohort = Cohort.objects.get(pk=from_existing_cohort_id)
        query = """
            SELECT DISTINCT person_id as actor_id
            FROM cohortpeople
            WHERE team_id = %(team_id)s AND cohort_id = %(from_cohort_id)s AND version = %(version)s
            ORDER BY person_id
        """
        params = {
            "team_id": cohort.team.pk,
            "from_cohort_id": existing_cohort.pk,
            "version": existing_cohort.version,
        }
        context = Filter(data=filter_data, team=cohort.team).hogql_context
    else:
        insight_type = filter_data.get("insight")
        query_builder: ActorBaseQuery

        if insight_type == INSIGHT_TRENDS:
            filter = Filter(data=filter_data, team=cohort.team)
            entity = get_target_entity(filter)
            query_builder = TrendsActors(cohort.team, entity, filter)
            context = filter.hogql_context
        elif insight_type == INSIGHT_STICKINESS:
            stickiness_filter = StickinessFilter(data=filter_data, team=cohort.team)
            entity = get_target_entity(stickiness_filter)
            query_builder = StickinessActors(cohort.team, entity, stickiness_filter)
            context = stickiness_filter.hogql_context
        elif insight_type == INSIGHT_FUNNELS:
            funnel_filter = Filter(data=filter_data, team=cohort.team)
            funnel_actor_class = get_funnel_actor_class(funnel_filter)
            query_builder = funnel_actor_class(filter=funnel_filter, team=cohort.team)
            context = funnel_filter.hogql_context
        elif insight_type == INSIGHT_PATHS:
            path_filter = PathFilter(data=filter_data, team=cohort.team)
            query_builder = PathsActors(path_filter, cohort.team, funnel_filter=None)
            context = path_filter.hogql_context
        elif insight_type == INSIGHT_LIFECYCLE:
            lifecycle_filter = LifecycleFilter(data=filter_data, team=cohort.team)
            query_builder = LifecycleActors(team=cohort.team, filter=lifecycle_filter)
            context = lifecycle_filter.hogql_context

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

    insert_actors_into_cohort_by_query(cohort, query, params, context)


def insert_actors_into_cohort_by_query(cohort: Cohort, query: str, params: Dict[str, Any], context: HogQLContext):
    try:
        sync_execute(
            INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID.format(cohort_table=PERSON_STATIC_COHORT_TABLE, query=query),
            {
                "cohort_id": cohort.pk,
                "_timestamp": datetime.now(),
                "team_id": cohort.team.pk,
                **context.values,
                **params,
            },
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

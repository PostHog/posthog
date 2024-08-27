import csv
from posthog.clickhouse.client.connection import Workload

from django.db import DatabaseError
from loginas.utils import is_impersonated_session
from sentry_sdk import start_span
import structlog

from posthog.models.activity_logging.activity_log import log_activity, Detail, changes_between, load_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.feature_flag.flag_matching import (
    FeatureFlagMatcher,
    FlagsMatcherCache,
    get_feature_flag_hash_key_overrides,
)
from posthog.models.person.person import PersonDistinctId
from posthog.models.property.property import Property, PropertyGroup
from posthog.queries.base import property_group_to_Q
from posthog.metrics import LABEL_TEAM_ID
from posthog.renderers import SafeJSONRenderer
from datetime import datetime
from typing import Any, cast, Optional

from django.conf import settings
from django.db.models import QuerySet, Prefetch, prefetch_related_objects, OuterRef, Subquery
from django.db.models.expressions import F
from django.utils import timezone
from rest_framework import serializers, viewsets, request, status
from posthog.api.utils import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers
from sentry_sdk.api import capture_exception

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.person import get_funnel_actor_class
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_target_entity
from posthog.client import sync_execute
from posthog.constants import (
    INSIGHT_FUNNELS,
    INSIGHT_LIFECYCLE,
    INSIGHT_PATHS,
    INSIGHT_STICKINESS,
    INSIGHT_TRENDS,
    LIMIT,
    OFFSET,
    PropertyOperatorType,
)
from posthog.hogql.constants import CSV_EXPORT_LIMIT
from posthog.event_usage import report_user_action
from posthog.hogql.context import HogQLContext
from posthog.models import Cohort, FeatureFlag, User, Person
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.cohort.util import get_dependent_cohorts, print_cohort_hogql_query
from posthog.models.cohort import CohortOrEmpty
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.lifecycle_filter import LifecycleFilter
from posthog.models.person.sql import (
    INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID,
    PERSON_STATIC_COHORT_TABLE,
)
from posthog.queries.actor_base_query import (
    ActorBaseQuery,
    get_serialized_people,
)
from posthog.queries.paths import PathsActors
from posthog.queries.person_query import PersonQuery
from posthog.queries.stickiness import StickinessActors
from posthog.queries.trends.trends_actors import TrendsActors
from posthog.queries.trends.lifecycle_actors import LifecycleActors
from posthog.queries.util import get_earliest_timestamp
from posthog.schema import ActorsQuery
from posthog.tasks.calculate_cohort import (
    calculate_cohort_from_list,
    insert_cohort_from_feature_flag,
    insert_cohort_from_insight_filter,
    update_cohort,
    insert_cohort_from_query,
)
from posthog.utils import format_query_params_absolute_url
from prometheus_client import Counter


API_COHORT_PERSON_BYTES_READ_FROM_POSTGRES_COUNTER = Counter(
    "api_cohort_person_bytes_read_from_postgres",
    "An estimate of how many bytes we've read from postgres to service person cohort endpoint.",
    labelnames=[LABEL_TEAM_ID],
)

logger = structlog.get_logger(__name__)


class CohortSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    earliest_timestamp_func = get_earliest_timestamp

    # If this cohort is an exposure cohort for an experiment
    experiment_set: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = Cohort
        fields = [
            "id",
            "name",
            "description",
            "groups",
            "deleted",
            "filters",
            "query",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "errors_calculating",
            "count",
            "is_static",
            "experiment_set",
        ]
        read_only_fields = [
            "id",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "errors_calculating",
            "count",
            "experiment_set",
        ]

    def _handle_static(self, cohort: Cohort, context: dict, validated_data: dict) -> None:
        request = self.context["request"]
        if request.FILES.get("csv"):
            self._calculate_static_by_csv(request.FILES["csv"], cohort)
        elif context.get("from_feature_flag_key"):
            insert_cohort_from_feature_flag.delay(cohort.pk, context["from_feature_flag_key"], self.context["team_id"])
        elif validated_data.get("query"):
            insert_cohort_from_query.delay(cohort.pk)
        else:
            filter_data = request.GET.dict()
            existing_cohort_id = context.get("from_cohort_id")
            if existing_cohort_id:
                filter_data = {**filter_data, "from_cohort_id": existing_cohort_id}
            if filter_data:
                insert_cohort_from_insight_filter.delay(cohort.pk, filter_data)

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context["request"]
        validated_data["created_by"] = request.user

        if not validated_data.get("is_static"):
            validated_data["is_calculating"] = True
        if validated_data.get("query") and validated_data.get("filters"):
            raise ValidationError("Cannot set both query and filters at the same time.")

        cohort = Cohort.objects.create(team_id=self.context["team_id"], **validated_data)

        if cohort.is_static:
            self._handle_static(cohort, self.context, validated_data)
        elif cohort.query is not None:
            raise ValidationError("Cannot create a dynamic cohort with a query. Set is_static to true.")
        else:
            update_cohort(cohort, initiating_user=request.user)

        report_user_action(request.user, "cohort created", cohort.get_analytics_metadata())
        return cohort

    def _calculate_static_by_csv(self, file, cohort: Cohort) -> None:
        decoded_file = file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded_file)
        distinct_ids_and_emails = [row[0] for row in reader if len(row) > 0 and row]
        calculate_cohort_from_list.delay(cohort.pk, distinct_ids_and_emails)

    def validate_query(self, query: Optional[dict]) -> Optional[dict]:
        if not query:
            return None
        if not isinstance(query, dict):
            raise ValidationError("Query must be a dictionary.")
        if query.get("kind") != "ActorsQuery":
            raise ValidationError(f"Query must be a ActorsQuery. Got: {query.get('kind')}")
        ActorsQuery.model_validate(query)
        return query

    def validate_filters(self, request_filters: dict):
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
                        nested_cohort = Cohort.objects.get(pk=prop.value, team_id=self.context["team_id"])
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

    def update(self, cohort: Cohort, validated_data: dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
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
                # De-attach from experiments
                cohort.experiment_set.set([])

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
                update_cohort(cohort, initiating_user=request.user)

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


class CohortViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer
    scope_object = "cohort"

    def safely_get_queryset(self, queryset) -> QuerySet:
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        return queryset.prefetch_related("experiment_set", "created_by", "team").order_by("-created_at")

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
        required_scopes=["cohort:read", "person:read"],
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

        query, params = PersonQuery(filter, team.pk, cohort=cohort).get_query(paginate=True)
        raw_result = sync_execute(
            query,
            {**params, **filter.hogql_context.values},
            workload=Workload.OFFLINE,  # this endpoint is only used by external API requests
        )
        actor_ids = [row[0] for row in raw_result]
        serialized_actors = get_serialized_people(team, actor_ids, distinct_id_limit=10)

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
                    actor["email"] = actor["properties"]["email"]  # type: ignore
                    del actor["properties"]["email"]
            serialized_actors = [
                {  # type: ignore
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

    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="Cohort", team_id=self.team_id, limit=limit, page=page)

        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]
        if not Cohort.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response("", status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="Cohort",
            team_id=self.team_id,
            item_ids=[str(item_id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

    def perform_create(self, serializer):
        serializer.save()
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=serializer.instance.id,
            scope="Cohort",
            activity="created",
            detail=Detail(name=serializer.instance.name),
        )

    def perform_update(self, serializer):
        instance_id = serializer.instance.id

        try:
            before_update = Cohort.objects.get(pk=instance_id)
        except Cohort.DoesNotExist:
            before_update = None

        serializer.save()

        changes = changes_between("Cohort", previous=before_update, current=serializer.instance)

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=instance_id,
            scope="Cohort",
            activity="updated",
            detail=Detail(changes=changes, name=serializer.instance.name),
        )


class LegacyCohortViewSet(CohortViewSet):
    param_derived_from_user_current_team = "project_id"


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


def insert_cohort_query_actors_into_ch(cohort: Cohort):
    context = HogQLContext(enable_select_queries=True, team_id=cohort.team.pk)
    query = print_cohort_hogql_query(cohort, context)
    insert_actors_into_cohort_by_query(cohort, query, {}, context)


def insert_cohort_actors_into_ch(cohort: Cohort, filter_data: dict):
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


def insert_actors_into_cohort_by_query(cohort: Cohort, query: str, params: dict[str, Any], context: HogQLContext):
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
            raise
        cohort.is_calculating = False
        cohort.errors_calculating = F("errors_calculating") + 1
        cohort.save(update_fields=["errors_calculating", "is_calculating"])
        capture_exception(err)


def get_cohort_actors_for_feature_flag(cohort_id: int, flag: str, team_id: int, batchsize: int = 1_000):
    # :TODO: Find a way to incorporate this into the same code path as feature flag evaluation
    try:
        feature_flag = FeatureFlag.objects.get(team_id=team_id, key=flag)
    except FeatureFlag.DoesNotExist:
        return []

    if not feature_flag.active or feature_flag.deleted or feature_flag.aggregation_group_type_index is not None:
        return []

    cohort = Cohort.objects.get(pk=cohort_id, team_id=team_id)
    matcher_cache = FlagsMatcherCache(team_id)
    uuids_to_add_to_cohort = []
    cohorts_cache: dict[int, CohortOrEmpty] = {}

    if feature_flag.uses_cohorts:
        # TODO: Consider disabling flags with cohorts for creating static cohorts
        # because this is currently a lot more inefficient for flag matching,
        # as we're required to go to the database for each person.
        cohorts_cache = {cohort.pk: cohort for cohort in Cohort.objects.filter(team_id=team_id, deleted=False)}

    default_person_properties = {}
    for condition in feature_flag.conditions:
        property_list = Filter(data=condition).property_groups.flat
        for property in property_list:
            default_person_properties.update(get_default_person_property(property, cohorts_cache))

    flag_property_conditions = [Filter(data=condition).property_groups for condition in feature_flag.conditions]
    flag_property_group = PropertyGroup(type=PropertyOperatorType.OR, values=flag_property_conditions)

    try:
        # QuerySet.Iterator() doesn't work with pgbouncer, it will load everything into memory and then stream
        # which doesn't work for us, so need a manual chunking here.
        # Because of this pgbouncer transaction pooling mode, we can't use server-side cursors.
        # We pre-filter all persons to be ones that will match the feature flag, so that we don't have to
        # iterate through all persons
        queryset = (
            Person.objects.filter(team_id=team_id)
            .filter(property_group_to_Q(team_id, flag_property_group, cohorts_cache=cohorts_cache))
            .order_by("id")
        )
        # get batchsize number of people at a time
        start = 0
        batch_of_persons = queryset[start : start + batchsize]
        while batch_of_persons:
            # TODO: Check if this subquery bulk fetch limiting is better than just doing a join for all distinct ids
            # OR, if row by row getting single distinct id is better
            # distinct_id = PersonDistinctId.objects.filter(person=person, team_id=team_id).values_list(
            #     "distinct_id", flat=True
            # )[0]
            distinct_id_subquery = Subquery(
                PersonDistinctId.objects.filter(person_id=OuterRef("person_id")).values_list("id", flat=True)[:3]
            )
            prefetch_related_objects(
                batch_of_persons,
                Prefetch(
                    "persondistinctid_set",
                    to_attr="distinct_ids_cache",
                    queryset=PersonDistinctId.objects.filter(id__in=distinct_id_subquery),
                ),
            )

            all_persons = list(batch_of_persons)
            if len(all_persons) == 0:
                break

            with start_span(op="batch_flag_matching_with_overrides"):
                for person in all_persons:
                    # ignore almost-deleted persons / persons with no distinct ids
                    if len(person.distinct_ids) == 0:
                        continue

                    distinct_id = person.distinct_ids[0]
                    person_overrides = {}
                    if feature_flag.ensure_experience_continuity:
                        # :TRICKY: This is inefficient because it tries to get the hashkey overrides one by one.
                        # But reusing functions is better for maintainability. Revisit optimising if this becomes a bottleneck.
                        person_overrides = get_feature_flag_hash_key_overrides(
                            team_id, [distinct_id], person_id_to_distinct_id_mapping={person.id: distinct_id}
                        )

                    try:
                        match = FeatureFlagMatcher(
                            [feature_flag],
                            distinct_id,
                            groups={},
                            cache=matcher_cache,
                            hash_key_overrides=person_overrides,
                            property_value_overrides={**default_person_properties, **person.properties},
                            group_property_value_overrides={},
                            cohorts_cache=cohorts_cache,
                        ).get_match(feature_flag)
                        if match.match:
                            uuids_to_add_to_cohort.append(str(person.uuid))
                    except (DatabaseError, ValueError, ValidationError):
                        logger.exception(
                            "Error evaluating feature flag for person", person_uuid=str(person.uuid), team_id=team_id
                        )
                    except Exception as err:
                        # matching errors are not fatal, so we just log them and move on.
                        # Capturing in sentry for now just in case there are some unexpected errors
                        # we did not account for.
                        capture_exception(err)

                    if len(uuids_to_add_to_cohort) >= batchsize:
                        cohort.insert_users_list_by_uuid(
                            uuids_to_add_to_cohort, insert_in_clickhouse=True, batchsize=batchsize
                        )
                        uuids_to_add_to_cohort = []

            start += batchsize
            batch_of_persons = queryset[start : start + batchsize]

        if len(uuids_to_add_to_cohort) > 0:
            cohort.insert_users_list_by_uuid(uuids_to_add_to_cohort, insert_in_clickhouse=True, batchsize=batchsize)

    except Exception as err:
        if settings.DEBUG or settings.TEST:
            raise
        capture_exception(err)


def get_default_person_property(prop: Property, cohorts_cache: dict[int, CohortOrEmpty]):
    default_person_properties = {}

    if prop.operator not in ("is_set", "is_not_set") and prop.type == "person":
        default_person_properties[prop.key] = ""
    elif prop.type == "cohort" and not isinstance(prop.value, list):
        try:
            parsed_cohort_id = int(prop.value)
        except (ValueError, TypeError):
            return None
        cohort = cohorts_cache.get(parsed_cohort_id)
        if cohort:
            return get_default_person_properties_for_cohort(cohort, cohorts_cache)
    return default_person_properties


def get_default_person_properties_for_cohort(cohort: Cohort, cohorts_cache: dict[int, CohortOrEmpty]) -> dict[str, str]:
    """
    Returns a dictionary of default person properties to use when evaluating a feature flag
    """
    default_person_properties = {}
    for property in cohort.properties.flat:
        default_person_properties.update(get_default_person_property(property, cohorts_cache))

    return default_person_properties

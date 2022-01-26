import json
from typing import Any, Dict, List, Optional, Type, Union, cast

from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from django.db.models import Count, Exists, OuterRef, Prefetch, QuerySet
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.timezone import now
from rest_framework import authentication, request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers
from rest_hooks.signals import raw_hook_event

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.queries.trends.person import ClickhouseTrendsActors
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_target_entity
from posthog.auth import PersonalAPIKeyAuthentication, TemporaryTokenAuthentication
from posthog.celery import update_cache_item_task
from posthog.constants import (
    INSIGHT_STICKINESS,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_STICKINESS,
    AvailableFeature,
)
from posthog.decorators import CacheType, cached_function
from posthog.event_usage import report_user_action
from posthog.filters import term_search_filter_sql
from posthog.models import (
    Action,
    ActionStep,
    CohortPeople,
    Entity,
    Event,
    Filter,
    Insight,
    Person,
    RetentionFilter,
)
from posthog.models.event import EventManager
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries import base, retention, stickiness, trends
from posthog.utils import generate_cache_key, get_safe_cache, should_refresh

from .person import get_person_name


class ActionStepSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.CharField(read_only=False, required=False)

    class Meta:
        model = ActionStep
        fields = [
            "id",
            "event",
            "tag_name",
            "text",
            "href",
            "selector",
            "url",
            "name",
            "url_matching",
            "properties",
        ]
        extra_kwargs = {
            "event": {"trim_whitespace": False},
            "tag_name": {"trim_whitespace": False},
            "text": {"trim_whitespace": False},
            "href": {"trim_whitespace": False},
            "name": {"trim_whitespace": False},
        }


class ActionSerializer(serializers.HyperlinkedModelSerializer):
    steps = ActionStepSerializer(many=True, required=False)
    created_by = UserBasicSerializer(read_only=True)
    is_calculating = serializers.SerializerMethodField()

    class Meta:
        model = Action
        fields = [
            "id",
            "name",
            "post_to_slack",
            "slack_message_format",
            "steps",
            "created_at",
            "created_by",
            "deleted",
            "is_calculating",
            "last_calculated_at",
            "team_id",
        ]
        extra_kwargs = {"team_id": {"read_only": True}}

    def get_is_calculating(self, action: Action) -> bool:
        return False

    def validate(self, attrs):
        instance = cast(Action, self.instance)
        exclude_args = {}
        if instance:
            include_args = {"team": instance.team}
            exclude_args = {"id": instance.pk}
        else:
            attrs["team_id"] = self.context["view"].team_id
            include_args = {"team_id": attrs["team_id"]}

        colliding_action_ids = list(
            Action.objects.filter(name=attrs["name"], deleted=False, **include_args)
            .exclude(**exclude_args)[:1]
            .values_list("id", flat=True)
        )
        if colliding_action_ids:
            raise serializers.ValidationError(
                {"name": f"This project already has an action with this name, ID {colliding_action_ids[0]}"},
                code="unique",
            )

        return attrs

    def create(self, validated_data: Any) -> Any:
        steps = validated_data.pop("steps", [])
        validated_data["created_by"] = self.context["request"].user
        instance = super().create(validated_data)

        for step in steps:
            ActionStep.objects.create(
                action=instance, **{key: value for key, value in step.items() if key not in ("isNew", "selection")},
            )

        report_user_action(validated_data["created_by"], "action created", instance.get_analytics_metadata())

        return instance

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:

        steps = validated_data.pop("steps", None)
        # If there's no steps property at all we just ignore it
        # If there is a step property but it's an empty array [], we'll delete all the steps
        if steps is not None:
            # remove steps not in the request
            step_ids = [step["id"] for step in steps if step.get("id")]
            instance.steps.exclude(pk__in=step_ids).delete()

            for step in steps:
                if step.get("id"):
                    step_instance = ActionStep.objects.get(pk=step["id"])
                    step_serializer = ActionStepSerializer(instance=step_instance)
                    step_serializer.update(step_instance, step)
                else:
                    ActionStep.objects.create(
                        action=instance,
                        **{key: value for key, value in step.items() if key not in ("isNew", "selection")},
                    )

        instance = super().update(instance, validated_data)
        instance.refresh_from_db()
        report_user_action(
            self.context["request"].user,
            "action updated",
            {
                **instance.get_analytics_metadata(),
                "updated_by_creator": self.context["request"].user == instance.created_by,
            },
        )
        return instance


class ActionViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    queryset = Action.objects.all()
    serializer_class = ActionSerializer
    authentication_classes = [
        TemporaryTokenAuthentication,
        PersonalAPIKeyAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    ordering = ["-last_calculated_at", "name"]

    def get_queryset(self):
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            try:
                from ee.models.action import EnterpriseAction
            except ImportError:
                pass
            else:
                search = self.request.GET.get("search", None)
                search_query, search_kwargs = term_search_filter_sql(self.search_fields, search)
                ee_actions = EnterpriseAction.objects.raw(
                    f"""
                    SELECT * 
                    FROM ee_enterpriseaction
                    FULL OUTER JOIN posthog_action ON posthog_action.id=ee_enterpriseaction.action_ptr_id
                    WHERE team_id = %(team_id)s {search_query}
                    ORDER BY last_calculated_at DESC NULLS LAST, name ASC
                    """,
                    params={"team_id": self.team_id, **search_kwargs},
                )
                return ee_actions

        queryset = super().get_queryset()  # Action
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        queryset = queryset.annotate(count=Count(TREND_FILTER_TYPE_EVENTS))
        queryset = queryset.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))
        return queryset.filter(team_id=self.team_id).order_by(*self.ordering)

    def get_serializer_class(self) -> Type[serializers.ModelSerializer]:
        serializer_class = self.serializer_class
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            try:
                from ee.api.ee_action import EnterpriseActionSerializer
            except ImportError:
                pass
            else:
                serializer_class = EnterpriseActionSerializer  # type: ignore
        return serializer_class

    def get_object(self):
        # Sync action and enterprise actions table if ee feature is available
        id = self.kwargs["id"]
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            try:
                from ee.models.action import EnterpriseAction
            except ImportError:
                pass
            else:
                enterprise_action = EnterpriseAction.objects.filter(id=id).first()
                if enterprise_action:
                    return enterprise_action
                non_enterprise_action = Action.objects.get(id=id)
                new_enterprise_action = EnterpriseAction(action_ptr_id=non_enterprise_action.id, description="")
                new_enterprise_action.__dict__.update(non_enterprise_action.__dict__)
                new_enterprise_action.save()
                return new_enterprise_action
        return Action.objects.get(id=id)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list: List[Dict[Any, Any]] = self.serializer_class(actions, many=True, context={"request": request}).data  # type: ignore
        return Response({"results": actions_list})

    @action(methods=["GET"], detail=False)
    def people(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        team = self.team
        filter = Filter(request=request, team=self.team)
        entity = get_target_entity(filter)

        actors, serialized_actors = ClickhouseTrendsActors(team, entity, filter).get_actors()

        current_url = request.get_full_path()
        next_url: Optional[str] = request.get_full_path()
        offset = filter.offset
        if len(actors) > 100 and next_url:
            if "offset" in next_url:
                next_url = next_url[1:]
                next_url = next_url.replace("offset=" + str(offset), "offset=" + str(offset + 100))
            else:
                next_url = request.build_absolute_uri(
                    "{}{}offset={}".format(next_url, "&" if "?" in next_url else "?", offset + 100)
                )
        else:
            next_url = None

        if request.accepted_renderer.format == "csv":
            csvrenderers.CSVRenderer.header = ["Distinct ID", "Internal ID", "Email", "Name", "Properties"]
            content = [
                {
                    "Name": get_person_name(person),
                    "Distinct ID": person.distinct_ids[0] if person.distinct_ids else "",
                    "Internal ID": str(person.uuid),
                    "Email": person.properties.get("email"),
                    "Properties": person.properties,
                }
                for person in actors
                if isinstance(person, Person)
            ]
            return Response(content)

        return Response(
            {
                "results": [{"people": serialized_actors[0:100], "count": len(serialized_actors[0:100])}],
                "next": next_url,
                "previous": current_url[1:],
            }
        )

    @action(methods=["GET"], detail=True)
    def count(self, request: request.Request, **kwargs) -> Response:
        action = self.get_object()
        query, params = format_action_filter(action)
        if query == "":
            return Response({"count": 0})

        results = sync_execute(
            "SELECT count(1) FROM events WHERE team_id = %(team_id)s AND timestamp < %(before)s AND timestamp > %(after)s AND {}".format(
                query
            ),
            {
                "team_id": action.team_id,
                "before": now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "after": (now() - relativedelta(months=3)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                **params,
            },
        )
        return Response({"count": results[0][0]})

    @action(methods=["GET"], detail=False)
    def trends(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        result = self._calculate_trends(request)
        return Response(result)

    @cached_function
    def _calculate_trends(self, request: request.Request) -> List[Dict[str, Any]]:
        team = self.team
        filter = Filter(request=request, team=self.team)
        if filter.insight == INSIGHT_STICKINESS or filter.shown_as == TRENDS_STICKINESS:
            earliest_timestamp_func = lambda team_id: Event.objects.earliest_timestamp(team_id)
            stickiness_filter = StickinessFilter(
                request=request, team=team, get_earliest_timestamp=earliest_timestamp_func
            )
            result = stickiness.Stickiness().run(stickiness_filter, team)
        else:
            result = trends.Trends().run(filter, team)

        dashboard_id = request.GET.get("from_dashboard", None)
        if dashboard_id:
            Insight.objects.filter(pk=dashboard_id).update(last_refresh=now())

        return result

    @action(methods=["GET"], detail=False)
    def retention(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        team = self.team
        properties = request.GET.get("properties", "{}")

        try:
            properties = json.loads(properties)
        except json.decoder.JSONDecodeError:
            raise ValidationError("Properties are unparsable!")

        data: Dict[str, Any] = {"properties": properties}
        start_entity_data = request.GET.get("start_entity", None)
        if start_entity_data:
            entity_data = json.loads(start_entity_data)
            data.update({"entites": [Entity({"id": entity_data["id"], "type": entity_data["type"]})]})

        data.update({"date_from": "-11d"})
        filter = RetentionFilter(data=data, team=self.team)

        result = retention.Retention().run(filter, team)
        return Response({"data": result})

    @action(methods=["GET"], detail=False)
    def funnel(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        team = self.team
        refresh = should_refresh(request)
        dashboard_id = request.GET.get("from_dashboard", None)

        filter = Filter(request=request, team=self.team)
        cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), team.pk))
        result = {"loading": True}

        if refresh:
            cache.delete(cache_key)
        else:
            cached_result = get_safe_cache(cache_key)
            if cached_result:
                task_id = cached_result.get("task_id", None)
                if not task_id:
                    return Response(cached_result["result"])
                else:
                    return Response(result)

        payload = {"filter": filter.toJSON(), "team_id": team.pk}
        task = update_cache_item_task.delay(cache_key, CacheType.FUNNEL, payload)
        if not task.ready():
            task_id = task.id
            cache.set(cache_key, {"task_id": task_id}, 180)  # task will be live for 3 minutes

        if dashboard_id:
            Insight.objects.filter(pk=dashboard_id).update(last_refresh=now())

        return Response(result)


def filter_by_type(entity: Entity, team: Team, filter: Filter) -> QuerySet:
    events: Union[EventManager, QuerySet] = Event.objects.none()
    if filter.session:
        events = Event.objects.filter(team=team).filter(base.filter_events(team.pk, filter)).add_person_id(team.pk)
    else:
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            actions = Action.objects.filter(deleted=False)
            try:
                actions.get(pk=entity.id)
            except Action.DoesNotExist:
                return events
        events = base.process_entity_for_events(entity, team_id=team.pk, order_by=None).filter(
            base.filter_events(team.pk, filter, entity)
        )
    return events


def _filter_cohort_breakdown(events: QuerySet, filter: Filter) -> QuerySet:
    if filter.breakdown_type == "cohort" and filter.breakdown_value != "all":
        events = events.filter(
            Exists(
                CohortPeople.objects.filter(
                    cohort_id=int(cast(str, filter.breakdown_value)), person_id=OuterRef("person_id"),
                ).only("id")
            )
        )
    return events


def _filter_person_prop_breakdown(events: QuerySet, filter: Filter) -> QuerySet:
    if filter.breakdown_type == "person":
        events = events.filter(
            Exists(
                Person.objects.filter(
                    **{"id": OuterRef("person_id"), f"properties__{filter.breakdown}": filter.breakdown_value,}
                ).only("id")
            )
        )
    return events


def _filter_event_prop_breakdown(events: QuerySet, filter: Filter) -> QuerySet:
    if filter.breakdown_type == "event":
        events = events.filter(**{f"properties__{filter.breakdown}": filter.breakdown_value,})
    return events


def calculate_people(
    team: Team, events: QuerySet, filter: Filter, request: request.Request, use_offset: bool = True
) -> QuerySet:
    events = events.values("person_id").distinct()
    events = _filter_cohort_breakdown(events, filter)
    events = _filter_person_prop_breakdown(events, filter)
    events = _filter_event_prop_breakdown(events, filter)
    people = Person.objects.filter(
        team=team,
        id__in=[p["person_id"] for p in (events[filter.offset : filter.offset + 100] if use_offset else events)],
    )
    people = base.filter_persons(team.id, request, people)  # type: ignore
    people = people.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
    return people


@receiver(post_save, sender=Action, dispatch_uid="hook-action-defined")
def action_defined(sender, instance, created, raw, using, **kwargs):
    """Trigger action_defined hooks on Action creation."""
    if created:
        raw_hook_event.send(
            sender=None,
            event_name="action_defined",
            instance=instance,
            payload=ActionSerializer(instance).data,
            user=instance.team,
        )


class LegacyActionViewSet(ActionViewSet):
    legacy_team_compatibility = True

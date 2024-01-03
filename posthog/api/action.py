from typing import Any, Dict, List, Optional, cast

from dateutil.relativedelta import relativedelta
from django.db.models import Count, Prefetch
from django.utils.timezone import now
from rest_framework import authentication, request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_target_entity
from posthog.auth import (
    JwtAuthentication,
    PersonalAPIKeyAuthentication,
    TemporaryTokenAuthentication,
)
from posthog.client import sync_execute
from posthog.constants import LIMIT, TREND_FILTER_TYPE_EVENTS
from posthog.event_usage import report_user_action
from posthog.hogql.hogql import HogQLContext
from posthog.models import Action, ActionStep, Filter, Person
from posthog.models.action.util import format_action_filter
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.queries.trends.trends_actors import TrendsActors

from .forbid_destroy_model import ForbidDestroyModel
from .person import get_person_name
from .tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin


class ActionStepSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.CharField(read_only=False, required=False)

    class Meta:
        model = ActionStep
        fields = [
            "id",
            "event",
            "tag_name",
            "text",
            "text_matching",
            "href",
            "href_matching",
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


class ActionSerializer(TaggedItemSerializerMixin, serializers.HyperlinkedModelSerializer):
    steps = ActionStepSerializer(many=True, required=False)
    created_by = UserBasicSerializer(read_only=True)
    is_calculating = serializers.SerializerMethodField()
    is_action = serializers.BooleanField(read_only=True, default=True)

    class Meta:
        model = Action
        fields = [
            "id",
            "name",
            "description",
            "tags",
            "post_to_slack",
            "slack_message_format",
            "steps",
            "created_at",
            "created_by",
            "deleted",
            "is_calculating",
            "last_calculated_at",
            "team_id",
            "is_action",
            "bytecode_error",
        ]
        read_only_fields = [
            "team_id",
            "bytecode_error",
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
                action=instance,
                **{key: value for key, value in step.items() if key not in ("isNew", "selection")},
            )

        report_user_action(
            validated_data["created_by"],
            "action created",
            instance.get_analytics_metadata(),
        )

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

        # bytecode might have been altered in the action steps
        instance.refresh_from_db(fields=["bytecode", "bytecode_error"])
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


class ActionViewSet(
    TaggedItemViewSetMixin,
    StructuredViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    queryset = Action.objects.all()
    serializer_class = ActionSerializer
    authentication_classes = [
        TemporaryTokenAuthentication,
        JwtAuthentication,
        PersonalAPIKeyAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]
    ordering = ["-last_calculated_at", "name"]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("created_by")
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

        queryset = queryset.annotate(count=Count(TREND_FILTER_TYPE_EVENTS))
        queryset = queryset.prefetch_related(Prefetch("steps", queryset=ActionStep.objects.order_by("id")))
        return queryset.filter(team_id=self.team_id).order_by(*self.ordering)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        actions = self.get_queryset()
        actions_list: List[Dict[Any, Any]] = self.serializer_class(
            actions, many=True, context={"request": request}
        ).data  # type: ignore
        return Response({"results": actions_list})

    # NOTE: Deprecated in favour of `persons/trends` endpoint
    # Once the old way of exporting CSVs is removed, this endpoint can be removed
    @action(methods=["GET"], detail=False)
    def people(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        team = self.team
        filter = Filter(request=request, team=self.team)
        if not filter.limit:
            filter = filter.shallow_clone({LIMIT: 100})

        entity = get_target_entity(filter)

        actors, serialized_actors, raw_count = TrendsActors(team, entity, filter).get_actors()

        current_url = request.get_full_path()
        next_url: Optional[str] = request.get_full_path()
        limit = filter.limit or 100
        offset = filter.offset
        if raw_count >= limit and next_url:
            if "offset" in next_url:
                next_url = next_url[1:]
                next_url = next_url.replace("offset=" + str(offset), "offset=" + str(offset + limit))
            else:
                next_url = f"{next_url}{'&' if '?' in next_url else '?'}offset={offset+limit}"
        else:
            next_url = None

        if request.accepted_renderer.format == "csv":
            content = [
                {
                    "Name": get_person_name(team, person),
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
                "results": [{"people": serialized_actors, "count": len(serialized_actors)}],
                "next": next_url,
                "previous": current_url[1:],
                "missing_persons": raw_count - len(serialized_actors),
            }
        )

    @action(methods=["GET"], detail=True)
    def count(self, request: request.Request, **kwargs) -> Response:
        action = self.get_object()
        # NOTE: never accepts cohort parameters so no need for explicit person_id_joined_alias
        hogql_context = HogQLContext(within_non_hogql_query=True, team_id=action.team_id)
        query, params = format_action_filter(team_id=action.team_id, action=action, hogql_context=hogql_context)
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
                **hogql_context.values,
            },
        )
        return Response({"count": results[0][0]})


class LegacyActionViewSet(ActionViewSet):
    legacy_team_compatibility = True

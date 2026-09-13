from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.db.models import QuerySet

from rest_framework import exceptions, mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.conversations.backend.models import TicketTopicOverride
from products.conversations.backend.pattern_detection import MIN_TOKEN_LENGTH, topics_for

if TYPE_CHECKING:
    from posthog.models import User

MAX_OVERRIDES_PER_TEAM = 50


class TicketTopicOverrideSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="Who added the override.")
    topic = serializers.CharField(
        max_length=200,
        help_text="One or two words, matched after the same normalization detection applies to ticket text: "
        "lowercase, stemmed, stopwords removed. 'Login failures' and 'login failure' are the same topic.",
    )

    class Meta:
        model = TicketTopicOverride
        fields = ["id", "kind", "topic", "notes", "enabled", "created_by", "created_at"]
        read_only_fields = ["id", "created_by", "created_at"]
        extra_kwargs = {
            "id": {"help_text": "Override UUID."},
            "kind": {"help_text": "mute: never open a pattern for this topic. watch: open one at the lowest bar."},
            "notes": {"help_text": "Why this override exists, for the next person who sees it."},
            "enabled": {"help_text": "A disabled override is kept but has no effect."},
            "created_at": {"help_text": "When the override was added."},
        }

    def validate_topic(self, value: str) -> str:
        # Store the topic in the form detection produces, or a human-typed "Login Failures" never
        # matches the "login failure" the detector compares against.
        normalized = sorted(topics_for(value), key=lambda t: (-t.count(" "), -len(t)))
        if not normalized:
            raise serializers.ValidationError(
                f"Enter at least one word of {MIN_TOKEN_LENGTH} or more letters that is not a common word."
            )
        return normalized[0]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        team_id = self.context["team_id"]
        topic = attrs.get("topic")
        if topic is not None:
            clash = TicketTopicOverride.objects.for_team(team_id).filter(topic=topic)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError({"topic": "An override for this topic already exists."})
        if self.instance is None:
            count = TicketTopicOverride.objects.for_team(team_id).count()
            if count >= MAX_OVERRIDES_PER_TEAM:
                raise serializers.ValidationError(
                    {"topic": f"A project can hold at most {MAX_OVERRIDES_PER_TEAM} overrides. Remove one first."}
                )
        return attrs

    def create(self, validated_data: dict[str, Any]) -> TicketTopicOverride:
        team_id = self.context["team_id"]
        # ModelSerializer.create goes through the default manager, which this environment-scoped
        # model refuses; the row has to be written with the environment's own id.
        return TicketTopicOverride.objects.for_team(team_id).create(
            team_id=team_id, created_by=self.context["request"].user, **validated_data
        )


class TicketTopicOverrideViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Per-topic instructions to the pattern detector. Same all-or-nothing ticket gate as patterns:
    an override steers what the whole inbox alerts on, so authoring one needs edit access to every
    ticket."""

    scope_object = "ticket"
    serializer_class = TicketTopicOverrideSerializer
    queryset = TicketTopicOverride.objects.unscoped()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def _is_ticket_restricted(self) -> bool:
        uac = cast(UserAccessControl, self.user_access_control)
        return bool(uac.blocked_resource_ids_by_scope.get("ticket")) or not uac.has_resource_access("ticket")

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = TicketTopicOverride.objects.for_team(self.team_id).select_related("created_by")
        if self._is_ticket_restricted():
            return queryset.none()
        return queryset.order_by("kind", "topic")

    def _assert_can_write(self) -> None:
        uac = cast(UserAccessControl, self.user_access_control)
        if self._is_ticket_restricted() or not uac.check_access_level_for_resource("ticket", "editor"):
            raise exceptions.PermissionDenied("You need edit access to every ticket to change pattern overrides.")

    def _track(self, event: str, instance: TicketTopicOverride) -> None:
        report_user_action(
            cast("User", self.request.user),
            event,
            {"kind": instance.kind, "enabled": instance.enabled},
            team=self.team,
            request=self.request,
        )

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        self._assert_can_write()
        self._track("support pattern override created", serializer.save())

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._assert_can_write()
        self._track("support pattern override updated", serializer.save())

    def perform_destroy(self, instance: TicketTopicOverride) -> None:
        self._assert_can_write()
        self._track("support pattern override deleted", instance)
        super().perform_destroy(instance)

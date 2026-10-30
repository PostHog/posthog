import re
from typing import Any

from django.db.models import F
from django.utils import timezone

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.conversations.backend.models import TicketMacro

SHORTCUT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_BODY_LENGTH = 10_000
# The composer escapes markdown punctuation, so {{customer.first_name}} arrives as \{\{customer\.first\_name\}\}.
_ESCAPED_MACRO_TOKEN = re.compile(r"\\{\\\{\s*((?:[a-z0-9]|\\[._])+)\s*\\}\\}", re.IGNORECASE)


def unescape_macro_tokens(body: str) -> str:
    def _token(match: re.Match[str]) -> str:
        key = match.group(1).replace("\\.", ".").replace("\\_", "_")
        return "{{" + key + "}}"

    return _ESCAPED_MACRO_TOKEN.sub(_token, body)


class TicketMacroSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, help_text="The user who created this macro.")
    name = serializers.CharField(max_length=200, help_text="Name shown in the macro list and the composer menu.")
    shortcut = serializers.CharField(
        max_length=50,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Slash command for this macro, without the leading slash. Lowercase letters, numbers, and "
        "hyphens. Unique within the project. Null when the macro has no shortcut.",
    )
    body = serializers.CharField(
        max_length=MAX_BODY_LENGTH,
        help_text="Reply text in markdown. May contain {{customer.first_name}}, {{customer.name}}, "
        "{{customer.email}}, {{agent.first_name}}, {{agent.name}}, and {{ticket.number}}. "
        "Variables are filled in when an agent inserts the macro.",
    )
    usage_count = serializers.IntegerField(
        read_only=True,
        help_text="How many times agents have inserted this macro.",
    )
    last_used_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When an agent last inserted this macro. Null if it has never been used.",
    )

    class Meta:
        model = TicketMacro
        fields = [
            "id",
            "name",
            "shortcut",
            "body",
            "usage_count",
            "last_used_at",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "usage_count",
            "last_used_at",
            "created_at",
            "updated_at",
            "created_by",
        ]
        extra_kwargs = {
            "id": {"help_text": "UUID of the macro."},
            "created_at": {"help_text": "When the macro was created."},
            "updated_at": {"help_text": "When the macro was last edited. Null until the first edit."},
        }

    def validate_shortcut(self, value: str | None) -> str | None:
        if value is None:
            return None
        shortcut = value.strip().lower()
        if not shortcut:
            return None
        if not SHORTCUT_RE.fullmatch(shortcut):
            raise serializers.ValidationError("Use lowercase letters, numbers, and hyphens.")
        return shortcut

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("This field may not be blank.")
        return name

    def validate_body(self, value: str) -> str:
        body = unescape_macro_tokens(value).strip()
        if not body:
            raise serializers.ValidationError("This field may not be blank.")
        return body

    def to_representation(self, instance: TicketMacro) -> dict[str, Any]:
        data = super().to_representation(instance)
        body = data.get("body")
        if isinstance(body, str):
            data["body"] = unescape_macro_tokens(body)
        return data

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        shortcut = attrs["shortcut"] if "shortcut" in attrs else getattr(self.instance, "shortcut", None)
        if shortcut:
            team_id = self.context["team_id"]
            existing = TicketMacro.objects.for_team(team_id).filter(shortcut=shortcut)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({"shortcut": "Another macro already uses this shortcut."})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> TicketMacro:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


@extend_schema_view(
    list=extend_schema(operation_id="conversations_macros_list"),
    retrieve=extend_schema(operation_id="conversations_macros_retrieve"),
    create=extend_schema(operation_id="conversations_macros_create"),
    partial_update=extend_schema(operation_id="conversations_macros_partial_update"),
    destroy=extend_schema(operation_id="conversations_macros_destroy"),
)
class TicketMacroViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    # "ticket" (not "conversation"): the conversation scope also authorizes AI conversation
    # endpoints, which saved replies have no business granting access to.
    scope_object = "ticket"
    # Built at import, before a request sets team context. safely_get_queryset scopes it.
    queryset = TicketMacro.objects.unscoped()
    serializer_class = TicketMacroSerializer
    # PATCH only: a full PUT would reset omitted fields.
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: Any) -> Any:
        return (
            queryset.filter(team_id=self.team_id)
            .select_related("created_by")
            .order_by("-usage_count", "-created_at", "-id")
        )

    def _track(self, event: str, instance: TicketMacro) -> None:
        report_user_action(
            self.request.user,
            event,
            {"id": str(instance.id), "name": instance.name, "has_shortcut": bool(instance.shortcut)},
            team=self.team,
            request=self.request,
        )

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        self._track("support macro created", serializer.save())

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._track("support macro updated", serializer.save())

    def perform_destroy(self, instance: TicketMacro) -> None:
        self._track("support macro deleted", instance)
        super().perform_destroy(instance)

    @extend_schema(request=None, responses=TicketMacroSerializer, operation_id="conversations_macros_used_create")
    @action(detail=True, methods=["post"], url_path="used")
    def used(self, request: Request, **kwargs: Any) -> Response:
        macro = self.get_object()
        TicketMacro.objects.for_team(self.team_id).filter(pk=macro.pk).update(
            usage_count=F("usage_count") + 1,
            last_used_at=timezone.now(),
        )
        macro.refresh_from_db()
        return Response(self.get_serializer(macro).data)

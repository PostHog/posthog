from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import BaseSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models.gateway import Gateway, validate_gateway_slug
from posthog.permissions import TeamMemberStrictManagementPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin


class GatewaySerializer(serializers.ModelSerializer):
    # Declared explicitly (rather than via the model field) so we can strip
    # before validating and surface a clean 400 — the model's RegexValidator
    # would otherwise reject untrimmed input before we get a chance to trim it.
    slug = serializers.CharField(
        max_length=64,
        help_text=(
            "Lowercase, URL-safe identifier (letters, digits, '-' or '_', no leading/trailing "
            "separator). This is the $ai_gateway_slug billing-attribution value the LLM gateway "
            "records for every request a bound credential makes."
        ),
    )
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Gateway
        fields = ["id", "slug", "created_at", "updated_at", "created_by"]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

    def validate_slug(self, value: str) -> str:
        value = (value or "").strip()
        try:
            validate_gateway_slug(value)
        except DjangoValidationError as e:
            raise ValidationError(e.messages[0])

        team = self.context["get_team"]()
        clashes = Gateway.objects.for_team(team.id).filter(slug=value)
        if self.instance is not None:
            clashes = clashes.exclude(pk=self.instance.pk)
        if clashes.exists():
            raise ValidationError(f'A gateway with the slug "{value}" already exists.')
        return value

    def create(self, validated_data: dict) -> Gateway:
        validated_data["team"] = self.context["get_team"]()
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class GatewayViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "llm_gateway"
    permission_classes = [TeamMemberStrictManagementPermission]
    serializer_class = GatewaySerializer
    # Placeholder safe at import time — the fail-closed manager would raise
    # without team context. safely_get_queryset re-scopes per request.
    queryset = Gateway.objects.unscoped()

    def _should_skip_parents_filter(self) -> bool:
        # safely_get_queryset already scopes via for_team(); the default parent
        # filter would re-filter on the raw URL team_id and miss a child
        # environment's parent-owned gateways.
        return True

    def safely_get_queryset(self, queryset: QuerySet[Gateway]) -> QuerySet[Gateway]:
        # Gateways live on the canonical (parent) team, so a child environment's
        # team_id must resolve to its parent — for_team() does that, where a raw
        # team_id filter would return nothing for a child environment.
        return Gateway.objects.for_team(self.team_id).select_related("created_by").order_by("slug")

    def perform_create(self, serializer: BaseSerializer) -> None:
        instance = serializer.save()
        report_user_action(
            self.request.user,
            "gateway created",
            {"gateway_id": str(instance.id), "slug": instance.slug},
            team=self.team,
        )

    def perform_destroy(self, instance: Gateway) -> None:
        gateway_id, slug = str(instance.id), instance.slug
        instance.delete()
        report_user_action(
            self.request.user,
            "gateway deleted",
            {"gateway_id": gateway_id, "slug": slug},
            team=self.team,
        )

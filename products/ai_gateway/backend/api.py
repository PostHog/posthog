from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models.gateway import Gateway, validate_gateway_slug
from posthog.models.oauth import OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.permissions import TeamMemberStrictManagementPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

_CREDENTIAL_TYPE_PERSONAL_API_KEY = "personal_api_key"
_CREDENTIAL_TYPE_OAUTH_APPLICATION = "oauth_application"


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
    bound_credentials_count = serializers.SerializerMethodField(
        help_text="Number of personal API keys and OAuth applications that attribute usage to this gateway."
    )

    class Meta:
        model = Gateway
        fields = ["id", "slug", "created_at", "updated_at", "created_by", "bound_credentials_count"]
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "bound_credentials_count"]

    def get_bound_credentials_count(self, gateway: Gateway) -> int:
        # Prefer the annotation added in list/retrieve; fall back to a count for
        # freshly created/updated instances that were never annotated.
        pak = getattr(gateway, "personal_api_key_count", None)
        oauth = getattr(gateway, "oauth_application_count", None)
        if pak is None or oauth is None:
            return gateway.personal_api_keys.count() + gateway.oauth_applications.count()
        return pak + oauth

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


class BoundPersonalAPIKeySerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True, help_text="Personal API key id.")
    label = serializers.CharField(read_only=True, help_text="The key's human-readable label.")  # type: ignore[assignment]
    user = UserBasicSerializer(read_only=True, help_text="The user the personal API key belongs to.")
    last_used_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the key was last used, if ever."
    )


class BoundOAuthApplicationSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True, help_text="OAuth application id.")
    name = serializers.CharField(read_only=True, help_text="The application's name.")
    client_id = serializers.CharField(read_only=True, help_text="The application's OAuth client id.")


class GatewayBoundCredentialsSerializer(serializers.Serializer):
    personal_api_keys = BoundPersonalAPIKeySerializer(
        many=True, read_only=True, help_text="Personal API keys bound to this gateway."
    )
    oauth_applications = BoundOAuthApplicationSerializer(
        many=True, read_only=True, help_text="OAuth applications bound to this gateway."
    )


class BindCredentialSerializer(serializers.Serializer):
    credential_type = serializers.ChoiceField(
        choices=[_CREDENTIAL_TYPE_PERSONAL_API_KEY, _CREDENTIAL_TYPE_OAUTH_APPLICATION],
        help_text="Which kind of credential to reassign.",
    )
    credential_id = serializers.CharField(help_text="Id of the credential to reassign to this gateway.")


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
        return (
            Gateway.objects.for_team(self.team_id)
            .select_related("created_by")
            .annotate(
                personal_api_key_count=Count("personal_api_keys", distinct=True),
                oauth_application_count=Count("oauth_applications", distinct=True),
            )
            .order_by("slug")
        )

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

    @extend_schema(responses=GatewayBoundCredentialsSerializer)
    @action(detail=True, methods=["get"])
    def credentials(self, request: Request, **kwargs: object) -> Response:
        """List the personal API keys and OAuth applications that attribute usage to this gateway."""
        gateway = self.get_object()
        payload = {
            "personal_api_keys": gateway.personal_api_keys.select_related("user").order_by("label"),
            "oauth_applications": gateway.oauth_applications.order_by("name"),
        }
        return Response(GatewayBoundCredentialsSerializer(payload).data)

    @extend_schema(request=BindCredentialSerializer, responses=GatewaySerializer)
    @action(detail=True, methods=["post"], url_path="bind_credential")
    def bind_credential(self, request: Request, **kwargs: object) -> Response:
        """Reassign a credential to this gateway.

        Only credentials already bound to one of this team's gateways can be moved —
        this manages attribution across the team's own gateways, not arbitrary keys."""
        gateway = self.get_object()
        serializer = BindCredentialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential_type = serializer.validated_data["credential_type"]
        credential_id = serializer.validated_data["credential_id"]

        team_gateway_ids = list(Gateway.objects.for_team(self.team_id).values_list("id", flat=True))
        if credential_type == _CREDENTIAL_TYPE_PERSONAL_API_KEY:
            credential = PersonalAPIKey.objects.filter(pk=credential_id, gateway_id__in=team_gateway_ids).first()
        else:
            credential = OAuthApplication.objects.filter(pk=credential_id, gateway_id__in=team_gateway_ids).first()

        if credential is None:
            raise ValidationError(
                {"credential_id": "Credential not found, or not bound to one of this team's gateways."}
            )

        credential.gateway = gateway
        credential.save(update_fields=["gateway"])
        report_user_action(
            self.request.user,
            "gateway credential bound",
            {"gateway_id": str(gateway.id), "slug": gateway.slug, "credential_type": credential_type},
            team=self.team,
        )
        # Re-fetch through the annotated queryset so bound_credentials_count is fresh.
        return Response(self.get_serializer(self.get_queryset().get(pk=gateway.pk)).data)

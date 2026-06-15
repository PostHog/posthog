from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.event_usage import report_user_action
from posthog.models.gateway import Gateway, validate_gateway_slug
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.permissions import TeamMemberStrictManagementPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.storage.gateway_credential_cache import clear_gateway_credential
from posthog.tasks.gateway_credential import reproject_oauth_application_gateway_credentials_task

_CREDENTIAL_TYPE_PROJECT_SECRET_API_KEY = "project_secret_api_key"
_CREDENTIAL_TYPE_OAUTH_APPLICATION = "oauth_application"
# The literal scope the gateway requires — wildcards don't subsume it (RFC #1103).
_GATEWAY_SCOPE = "llm_gateway:read"


class GatewayHasBoundCredentialsError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Unassign the credentials bound to this gateway before deleting it."
    default_code = "gateway_has_bound_credentials"


def _canonical_team(team: Team) -> Team:
    """The parent team that owns project-scoped resources (a child env resolves up)."""
    return team if team.parent_team_id is None else Team.objects.get(id=team.parent_team_id)


def _scoped_teams_for_request(request: Request) -> list[int] | None:
    """The token's project scope, or None for unscoped/session auth."""
    authr = getattr(request, "successful_authenticator", None)
    if isinstance(authr, OAuthAccessTokenAuthentication):
        return authr.access_token.scoped_teams
    if isinstance(authr, PersonalAPIKeyAuthentication):
        return authr.personal_api_key.scoped_teams
    return None


class GatewayManagementPermission(TeamMemberStrictManagementPermission):
    """Authorize against the canonical (parent) team that owns the gateway — else a
    child-env admin could manage the parent's shared gateway via the child's URL team_id."""

    # Listing assignable keys is a read any member can do; binding/unbinding and gateway
    # mutations manage shared team resources, so they're admin-only.
    member_level_actions = {"assignable_credentials"}

    def has_permission(self, request: Request, view: APIView) -> bool:
        canonical = _canonical_team(view.team)  # type: ignore[attr-defined]
        # APIScopePermission checks scoped_teams against the URL team (maybe a child env).
        # Re-check against the owner so a child-scoped token can't manage parent gateways.
        scoped_teams = _scoped_teams_for_request(request)
        if scoped_teams and canonical.id not in scoped_teams:
            return False
        level = view.user_permissions.team(canonical).effective_membership_level  # type: ignore[attr-defined]
        if level is None:
            return False
        member_ok = request.method in SAFE_METHODS or getattr(view, "action", None) in self.member_level_actions
        minimum = OrganizationMembership.Level.MEMBER if member_ok else OrganizationMembership.Level.ADMIN
        return level >= minimum


class GatewaySerializer(serializers.ModelSerializer):
    # Declared explicitly so we can strip before validating — the model's RegexValidator
    # would otherwise reject untrimmed input first.
    slug = serializers.CharField(
        max_length=64,
        help_text=(
            "Lowercase, URL-safe identifier (letters, digits, '-' or '_', no leading/trailing "
            "separator). This is the $ai_gateway_slug billing-attribution value the LLM gateway "
            "records for every request a bound credential makes."
        ),
    )
    # Null for auto-provisioned and backfilled gateways, which have no creating user.
    created_by = UserBasicSerializer(read_only=True, allow_null=True)
    bound_credentials_count = serializers.SerializerMethodField(
        help_text="Number of project secret keys and OAuth applications that attribute usage to this gateway."
    )

    class Meta:
        model = Gateway
        fields = ["id", "slug", "created_at", "updated_at", "created_by", "bound_credentials_count"]
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "bound_credentials_count"]

    def get_bound_credentials_count(self, gateway: Gateway) -> int:
        # Prefer the annotation added in list/retrieve; fall back to a count for
        # freshly created/updated instances that were never annotated.
        secret_keys = getattr(gateway, "project_secret_api_key_count", None)
        oauth = getattr(gateway, "oauth_application_count", None)
        if secret_keys is None or oauth is None:
            return gateway.project_secret_api_keys.count() + gateway.oauth_applications.count()
        return secret_keys + oauth

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


class BoundProjectSecretAPIKeySerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True, help_text="Project secret API key id.")
    label = serializers.CharField(read_only=True, help_text="The key's human-readable label.")  # type: ignore[assignment]
    last_used_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the key was last used, if ever."
    )


class BoundOAuthApplicationSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True, help_text="OAuth application id.")
    name = serializers.CharField(read_only=True, help_text="The application's name.")
    client_id = serializers.CharField(read_only=True, help_text="The application's OAuth client id.")


class GatewayBoundCredentialsSerializer(serializers.Serializer):
    project_secret_api_keys = BoundProjectSecretAPIKeySerializer(
        many=True, read_only=True, help_text="Project secret keys bound to this gateway."
    )
    oauth_applications = BoundOAuthApplicationSerializer(
        many=True, read_only=True, help_text="OAuth applications bound to this gateway."
    )


class UnassignCredentialSerializer(serializers.Serializer):
    credential_type = serializers.ChoiceField(
        choices=[_CREDENTIAL_TYPE_PROJECT_SECRET_API_KEY, _CREDENTIAL_TYPE_OAUTH_APPLICATION],
        help_text="Which kind of credential to unassign.",
    )
    credential_id = serializers.CharField(help_text="Id of the credential to unassign from this gateway.")


class AssignableCredentialSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True, help_text="Project secret API key id.")
    label = serializers.CharField(read_only=True, help_text="The key's human-readable label.")  # type: ignore[assignment]
    last_used_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the key was last used, if ever."
    )


class AssignCredentialSerializer(serializers.Serializer):
    credential_id = serializers.CharField(
        help_text="Id of one of the team's unassigned project secret keys to assign to this gateway."
    )


class GatewayViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "llm_gateway"
    permission_classes = [GatewayManagementPermission]
    serializer_class = GatewaySerializer
    # Placeholder safe at import time — the fail-closed manager would raise
    # without team context. safely_get_queryset re-scopes per request.
    queryset = Gateway.objects.unscoped()

    def _should_skip_parents_filter(self) -> bool:
        # safely_get_queryset already scopes via for_team(); the default parent filter
        # would re-filter on the raw URL team_id and miss parent-owned gateways.
        return True

    def safely_get_queryset(self, queryset: QuerySet[Gateway]) -> QuerySet[Gateway]:
        # Gateways live on the canonical (parent) team; for_team() resolves a child env's
        # team_id to its parent, where a raw team_id filter would return nothing.
        return (
            Gateway.objects.for_team(self.team_id)
            .select_related("created_by")
            .annotate(
                project_secret_api_key_count=Count("project_secret_api_keys", distinct=True),
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
        # The credential gateway FKs are SET_NULL, so deleting would silently unbind
        # every key. Require an explicit drain first and surface a 409 otherwise.
        if instance.project_secret_api_keys.exists() or instance.oauth_applications.exists():
            raise GatewayHasBoundCredentialsError()
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
        """List the project secret keys and OAuth applications that attribute usage to this gateway."""
        gateway = self.get_object()
        payload = {
            "project_secret_api_keys": gateway.project_secret_api_keys.order_by("label"),
            "oauth_applications": gateway.oauth_applications.order_by("name"),
        }
        return Response(GatewayBoundCredentialsSerializer(payload).data)

    @extend_schema(request=UnassignCredentialSerializer, responses=GatewaySerializer)
    @action(detail=True, methods=["post"], url_path="unassign_credential")
    def unassign_credential(self, request: Request, **kwargs: object) -> Response:
        """Remove a credential from this gateway, leaving it unassigned (admin-only)."""
        gateway = self.get_object()
        serializer = UnassignCredentialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential_type = serializer.validated_data["credential_type"]
        credential_id = serializer.validated_data["credential_id"]

        # Scoped to credentials bound to THIS gateway — that's the authorization boundary.
        model = ProjectSecretAPIKey if credential_type == _CREDENTIAL_TYPE_PROJECT_SECRET_API_KEY else OAuthApplication
        credential = model.objects.filter(  # nosemgrep: idor-lookup-without-user
            pk=credential_id,  # nosemgrep: idor-taint-user-input-to-user-model
            gateway_id=gateway.id,
        ).first()
        if credential is None:
            raise ValidationError({"credential_id": "Credential not found, or not assigned to this gateway."})

        credential.gateway = None
        credential.save(update_fields=["gateway"])

        # Explicit revocation: clear the now-unbound credential's blob synchronously so it
        # can't keep authenticating during the post_save signal's async window. A secret key
        # has one blob; an OAuth app's tokens each have one, so reproject the app (now unbound
        # → cleared). The signal-fired task stays as the idempotent backstop.
        if settings.AI_GATEWAY_REDIS_URL:
            if credential_type == _CREDENTIAL_TYPE_PROJECT_SECRET_API_KEY:
                clear_gateway_credential(credential)
            else:
                reproject_oauth_application_gateway_credentials_task(str(credential.id))

        report_user_action(
            self.request.user,
            "gateway credential unassigned",
            {"gateway_id": str(gateway.id), "slug": gateway.slug, "credential_type": credential_type},
            team=self.team,
        )
        # Re-fetch through the annotated queryset so bound_credentials_count is fresh.
        return Response(self.get_serializer(self.get_queryset().get(pk=gateway.pk)).data)

    @extend_schema(responses=AssignableCredentialSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def assignable_credentials(self, request: Request, **kwargs: object) -> Response:
        """The team's project secret keys that carry the llm_gateway:read scope but aren't assigned to a gateway yet."""
        keys = ProjectSecretAPIKey.objects.filter(
            team=_canonical_team(self.team), gateway__isnull=True, scopes__contains=[_GATEWAY_SCOPE]
        ).order_by("label")
        return Response(AssignableCredentialSerializer(keys, many=True).data)

    @extend_schema(request=AssignCredentialSerializer, responses=GatewaySerializer)
    @action(detail=True, methods=["post"], url_path="assign_credential")
    def assign_credential(self, request: Request, **kwargs: object) -> Response:
        """Assign one of the team's unassigned project secret keys to this gateway (admin-only).

        The key must belong to the gateway's canonical team, so a key from another
        project can't be attributed here."""
        gateway = self.get_object()
        serializer = AssignCredentialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential_id = serializer.validated_data["credential_id"]

        key = ProjectSecretAPIKey.objects.filter(
            pk=credential_id,
            team=_canonical_team(self.team),
            gateway__isnull=True,
            scopes__contains=[_GATEWAY_SCOPE],
        ).first()
        if key is None:
            raise ValidationError(
                {
                    "credential_id": "Key not found, not on this project, already assigned, "
                    "or missing the llm_gateway:read scope."
                }
            )

        key.gateway = gateway
        key.save(update_fields=["gateway"])
        report_user_action(
            self.request.user,
            "gateway credential assigned",
            {"gateway_id": str(gateway.id), "slug": gateway.slug},
            team=self.team,
        )
        # Re-fetch through the annotated queryset so bound_credentials_count is fresh.
        return Response(self.get_serializer(self.get_queryset().get(pk=gateway.pk)).data)

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models.gateway import Gateway, validate_gateway_slug
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.permissions import TeamMemberStrictManagementPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

_CREDENTIAL_TYPE_PERSONAL_API_KEY = "personal_api_key"
_CREDENTIAL_TYPE_OAUTH_APPLICATION = "oauth_application"
# The literal scope the gateway requires — wildcards don't subsume it (RFC #1103).
_GATEWAY_SCOPE = "llm_gateway:read"


def _canonical_team(team: Team) -> Team:
    """The parent team that owns project-scoped resources (a child env resolves up)."""
    return team if team.parent_team_id is None else Team.objects.get(id=team.parent_team_id)


class GatewayManagementPermission(TeamMemberStrictManagementPermission):
    """Authorize against the canonical (parent) team that owns the gateway.

    Gateways are project-scoped and live on the parent team; a child environment's
    URL team_id resolves to that parent in the queryset. Measuring membership against
    the URL team would let a child-environment-only admin manage the parent's shared
    gateway, so resolve the parent and check there — matching the resource's owner.
    """

    # These touch only the requesting user's own key (re-checked per-key in the
    # action), so they're member-level — unlike the admin-gated gateway mutations
    # and the cross-gateway credential move.
    member_level_actions = {"assignable_credentials", "assign_credential", "unassign_credential"}

    def has_permission(self, request: Request, view: APIView) -> bool:
        level = view.user_permissions.team(_canonical_team(view.team)).effective_membership_level  # type: ignore[attr-defined]
        if level is None:
            return False
        member_ok = request.method in SAFE_METHODS or getattr(view, "action", None) in self.member_level_actions
        minimum = OrganizationMembership.Level.MEMBER if member_ok else OrganizationMembership.Level.ADMIN
        return level >= minimum


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
    # Null for auto-provisioned and backfilled gateways, which have no creating user.
    created_by = UserBasicSerializer(read_only=True, allow_null=True)
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


class AssignableCredentialSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True, help_text="Personal API key id.")
    label = serializers.CharField(read_only=True, help_text="The key's human-readable label.")  # type: ignore[assignment]
    last_used_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the key was last used, if ever."
    )


class AssignCredentialSerializer(serializers.Serializer):
    credential_id = serializers.CharField(
        help_text="Id of one of your own unassigned personal API keys to assign to this gateway."
    )


class GatewayViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "llm_gateway"
    permission_classes = [GatewayManagementPermission]
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

        # Tenant isolation here is by gateway, not user: this is an admin-gated action
        # (TeamMemberStrictManagementPermission) that manages which of the team's gateways a
        # credential attributes to, so it must reach credentials owned by any team member.
        # gateway_id__in restricts the lookup to credentials already bound to THIS team's
        # gateways, which is the authorization boundary — a user filter would be wrong here.
        team_gateway_ids = list(Gateway.objects.for_team(self.team_id).values_list("id", flat=True))
        if credential_type == _CREDENTIAL_TYPE_PERSONAL_API_KEY:
            credential = PersonalAPIKey.objects.filter(  # nosemgrep: idor-lookup-without-user
                pk=credential_id,  # nosemgrep: idor-taint-user-input-to-user-model
                gateway_id__in=team_gateway_ids,
            ).first()
        else:
            credential = OAuthApplication.objects.filter(  # nosemgrep: idor-lookup-without-user
                pk=credential_id,  # nosemgrep: idor-taint-user-input-to-user-model
                gateway_id__in=team_gateway_ids,
            ).first()

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

    def _is_project_admin(self) -> bool:
        level = self.user_permissions.team(_canonical_team(self.team)).effective_membership_level
        return level is not None and level >= OrganizationMembership.Level.ADMIN

    @extend_schema(request=BindCredentialSerializer, responses=GatewaySerializer)
    @action(detail=True, methods=["post"], url_path="unassign_credential")
    def unassign_credential(self, request: Request, **kwargs: object) -> Response:
        """Remove a credential from this gateway, leaving it unassigned.

        You can remove your own personal key; removing anyone else's key (or an OAuth
        application) is admin-only, like the cross-gateway move."""
        gateway = self.get_object()
        serializer = BindCredentialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential_type = serializer.validated_data["credential_type"]
        credential_id = serializer.validated_data["credential_id"]

        # Scoped to credentials bound to THIS gateway — that's the authorization boundary.
        if credential_type == _CREDENTIAL_TYPE_PERSONAL_API_KEY:
            credential = PersonalAPIKey.objects.filter(  # nosemgrep: idor-lookup-without-user
                pk=credential_id,  # nosemgrep: idor-taint-user-input-to-user-model
                gateway_id=gateway.id,
            ).first()
            owns = credential is not None and credential.user_id == request.user.id
        else:
            credential = OAuthApplication.objects.filter(  # nosemgrep: idor-lookup-without-user
                pk=credential_id,  # nosemgrep: idor-taint-user-input-to-user-model
                gateway_id=gateway.id,
            ).first()
            owns = False  # OAuth apps are org-managed; no per-user self-service path.

        if credential is None:
            raise ValidationError({"credential_id": "Credential not found, or not assigned to this gateway."})
        if not owns and not self._is_project_admin():
            raise PermissionDenied("Only project admins can remove another member's key.")

        credential.gateway = None
        credential.save(update_fields=["gateway"])
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
        """Your personal API keys that carry the llm_gateway:read scope but aren't assigned to a gateway yet."""
        keys = PersonalAPIKey.objects.filter(
            user=request.user, gateway__isnull=True, scopes__contains=[_GATEWAY_SCOPE]
        ).order_by("label")
        return Response(AssignableCredentialSerializer(keys, many=True).data)

    @extend_schema(request=AssignCredentialSerializer, responses=GatewaySerializer)
    @action(detail=True, methods=["post"], url_path="assign_credential")
    def assign_credential(self, request: Request, **kwargs: object) -> Response:
        """Assign one of your own unassigned personal API keys to this gateway.

        An unbound key has no team boundary, so only its owner may assign it — hence
        the user filter (unlike bind_credential, which moves the team's already-bound keys)."""
        gateway = self.get_object()
        serializer = AssignCredentialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential_id = serializer.validated_data["credential_id"]

        key = PersonalAPIKey.objects.filter(
            pk=credential_id,  # nosemgrep: idor-taint-user-input-to-user-model
            user=request.user,
            gateway__isnull=True,
            scopes__contains=[_GATEWAY_SCOPE],
        ).first()
        if key is None:
            raise ValidationError(
                {"credential_id": "Key not found, not yours, already assigned, or missing the llm_gateway:read scope."}
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

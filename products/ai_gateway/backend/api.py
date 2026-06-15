from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.gateway import Gateway, validate_gateway_slug
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.permissions import TeamMemberStrictManagementPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin


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
    child-env admin could manage the parent's shared gateway via the child's URL team_id.
    Reads are open to any member; renaming the gateway is admin-only."""

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
        minimum = (
            OrganizationMembership.Level.MEMBER
            if request.method in SAFE_METHODS
            else OrganizationMembership.Level.ADMIN
        )
        return level >= minimum


class GatewaySerializer(serializers.ModelSerializer):
    # Declared explicitly so we can strip before validating — the model's RegexValidator
    # would otherwise reject untrimmed input first.
    slug = serializers.CharField(
        max_length=64,
        help_text=(
            "Lowercase, URL-safe identifier (letters, digits, '-' or '_', no leading/trailing "
            "separator). This is the $ai_gateway_slug billing-attribution value the LLM gateway "
            "records for every request a credential with the llm_gateway:read scope makes."
        ),
    )
    # Null for auto-provisioned gateways, which have no creating user.
    created_by = UserBasicSerializer(read_only=True, allow_null=True)

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


class GatewayViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    # One gateway per team: list/read it and rename its slug. Creation is handled by
    # provisioning, and there's nothing to delete or bind credentials to.
    http_method_names = ["get", "patch", "head", "options"]
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
        return Gateway.objects.for_team(self.team_id).select_related("created_by").order_by("slug")

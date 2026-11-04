from typing import Any, cast

from django.db import transaction
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.organization_personal_api_key_actions import (
    KeyActionOutcome,
    KeyActionResult,
    KeyReachResolver,
    OrganizationPersonalAPIKeyActions,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey, get_organization_personal_api_keys
from posthog.permissions import (
    OrganizationAdminReadPermissions,
    PremiumFeaturePermission,
    TimeSensitiveActionPermission,
)
from posthog.tasks.email import send_personal_api_keys_changed_by_org_admin


class OrganizationPersonalAPIKeyOwnerSerializer(serializers.Serializer):
    first_name = serializers.CharField(read_only=True, help_text="First name of the key's owner.")
    last_name = serializers.CharField(read_only=True, help_text="Last name of the key's owner.")
    email = serializers.EmailField(read_only=True, help_text="Email address of the key's owner.")


class OrganizationPersonalAPIKeyProjectScopeSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Project (team) ID the key is scoped to.")
    name = serializers.CharField(help_text="Name of the project the key is scoped to.")


class OrganizationPersonalAPIKeyAccessScopeSerializer(serializers.Serializer):
    type = serializers.CharField(
        help_text="Breadth of access: 'all' (every project the owner can reach), 'organization' "
        "(this whole organization), or 'projects' (specific projects listed under 'projects')."
    )
    projects = OrganizationPersonalAPIKeyProjectScopeSerializer(
        many=True,
        required=False,
        help_text="Projects within this organization the key is scoped to, present only when type is 'projects'.",
    )


class OrganizationPersonalAPIKeySerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True, help_text="Unique ID of the key.")
    owner = OrganizationPersonalAPIKeyOwnerSerializer(
        source="user", read_only=True, help_text="The organization member who owns this key."
    )
    mask_value = serializers.CharField(
        read_only=True,
        help_text="Masked, display-safe hint of the key value (e.g. 'phx_***1234'). Not the secret. "
        "The owner sees the same masked value in their own settings, so it can be used to identify a key.",
    )
    scopes = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="API scopes granted to the key, e.g. 'insight:read'. A single '*' means full access.",
    )
    access_scope = serializers.SerializerMethodField(help_text="Where the key's scopes apply within this organization.")
    reaches_other_organizations = serializers.SerializerMethodField(
        help_text="Whether the key also works in at least one other organization its owner belongs to."
    )
    last_used_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the key was last used to authenticate, if ever."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the key was created.")

    class Meta:
        model = PersonalAPIKey
        fields = [
            "id",
            "owner",
            "mask_value",
            "scopes",
            "access_scope",
            "reaches_other_organizations",
            "last_used_at",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OrganizationPersonalAPIKeyAccessScopeSerializer)
    def get_access_scope(self, key: PersonalAPIKey) -> dict[str, Any]:
        team_names: dict[int, str] = self.context["team_names"]

        if key.scoped_teams:
            projects = [
                {"id": team_id, "name": team_names[team_id]} for team_id in key.scoped_teams if team_id in team_names
            ]
            if projects:
                return {"type": "projects", "projects": projects}

        if not key.scoped_organizations and not key.scoped_teams:
            return {"type": "all"}

        return {"type": "organization"}

    @extend_schema_field(serializers.BooleanField())
    def get_reaches_other_organizations(self, key: PersonalAPIKey) -> bool:
        resolver: KeyReachResolver = self.context["reach_resolver"]
        organization_id = str(self.context["get_organization"]().id)
        return bool(resolver.reach(key, organization_id).other_organization_ids)


class OrganizationPersonalAPIKeyActionResultSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(
        choices=KeyActionOutcome.choices,
        help_text="What happened to the key. 'rolled': the key has a new secret that nobody sees, and the old "
        "secret no longer works anywhere. 'deleted': the key no longer exists. 'access_removed': the key no "
        "longer works in this organization and keeps working in the owner's other organizations.",
    )


@extend_schema(extensions={"x-product": "platform_features"})
class OrganizationPersonalAPIKeyViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    serializer_class = OrganizationPersonalAPIKeySerializer
    permission_classes = [OrganizationAdminReadPermissions, PremiumFeaturePermission, TimeSensitiveActionPermission]
    premium_feature = AvailableFeature.ORGANIZATION_SECURITY_SETTINGS
    queryset = PersonalAPIKey.objects.none()
    # PersonalAPIKey has no organization_id; the parent lookup resolves through the owner's membership.
    filter_rewrite_rules = {"organization_id": "user__organization_membership__organization_id"}

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return get_organization_personal_api_keys(self.organization).order_by("-last_used_at", "-created_at")

    def dangerously_get_object(self) -> PersonalAPIKey:
        # The object permission checks read the organization from the object. They cannot run on a key, because a
        # key belongs to a user and can reach several organizations. The view permissions already require an admin
        # of the organization in the URL, and this queryset holds only the keys that reach that organization.
        key = self.filter_queryset(self.get_queryset()).filter(pk=self.kwargs["pk"]).first()
        if key is None:
            raise NotFound()
        return key

    def get_serializer(self, *args: Any, **kwargs: Any) -> serializers.BaseSerializer:
        context = kwargs.setdefault("context", self.get_serializer_context())
        if kwargs.get("many") and args:
            context["reach_resolver"] = KeyReachResolver.for_keys(list(args[0]))
        return super().get_serializer(*args, **kwargs)

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["team_names"] = {team.id: team.name for team in self.organization.teams.all()}
        return context

    @extend_schema(
        operation_id="organization_personal_api_keys_roll",
        request=None,
        responses={200: OrganizationPersonalAPIKeyActionResultSerializer},
    )
    @action(methods=["POST"], detail=True)
    def roll(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        key = self.get_object()
        return self._action_response(self._key_actions().roll(key.id))

    @extend_schema(
        operation_id="organization_personal_api_keys_revoke",
        request=None,
        responses={200: OrganizationPersonalAPIKeyActionResultSerializer},
    )
    @action(methods=["POST"], detail=True)
    def revoke(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        key = self.get_object()
        return self._action_response(self._key_actions().revoke(key.id))

    def _key_actions(self) -> OrganizationPersonalAPIKeyActions:
        return OrganizationPersonalAPIKeyActions(self.organization, cast(User, self.request.user))

    def _action_response(self, result: KeyActionResult | None) -> Response:
        if result is None:
            raise NotFound()
        organization_id = str(self.organization.id)
        acting_user_email = cast(User, self.request.user).email
        changes = [{"label": result.label, "mask_value": result.mask_value, "outcome": str(result.outcome)}]
        transaction.on_commit(
            lambda: send_personal_api_keys_changed_by_org_admin.delay(
                user_id=result.owner_id,
                organization_id=organization_id,
                acting_user_email=acting_user_email,
                changes=changes,
            )
        )
        return Response(OrganizationPersonalAPIKeyActionResultSerializer({"outcome": result.outcome}).data)

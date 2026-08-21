"""Ownership of access control rules by an external manager, currently Terraform only.

Two problems are solved here. A rule that Terraform owns should not be editable in PostHog,
because the next `terraform apply` silently reverts the edit. And Terraform has to be able to
say which rules it owns, because it only writes a rule when that rule changed - a rule that is
already correct is never written, so it would never be stamped.

The claim endpoint answers the second problem: the provider calls it while refreshing state,
which happens on every plan, including for rules with no diff.
"""

from typing import TYPE_CHECKING, Any, cast

from django.utils.timezone import now

from rest_framework import exceptions, serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.documentation import extend_schema
from posthog.event_usage import EventSource, get_event_source
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.rbac.user_access_control import UserAccessControl
from posthog.scopes import API_SCOPE_OBJECTS, INTERNAL_API_SCOPE_OBJECTS

from products.access_control.backend.models import TeamAccessControlConfig, terraform_lock_enabled

from ee.models.rbac.access_control import AccessControl, AccessControlManager

if TYPE_CHECKING:
    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


LOCKED_RULE_MESSAGE = (
    "Terraform manages this access control rule. Change it in your Terraform configuration, "
    "or turn off the Terraform lock in project settings."
)


def request_manager(request: Request | None) -> str | None:
    """The external manager a request speaks for, or None for every other caller."""
    if request is None:
        return None
    if get_event_source(request) == EventSource.TERRAFORM:
        return AccessControlManager.TERRAFORM
    return None


def assert_rule_is_editable(*, request: Request | None, team: Team, instance: AccessControl | None) -> None:
    """Refuse to change a managed rule when the team locked them.

    Called for updates and deletes, never for creating a rule that did not exist: a rule for a
    subject Terraform does not declare is not drift, so it stays editable.
    """
    if instance is None or not instance.managed_by:
        return
    if request_manager(request) == instance.managed_by:
        return
    if not terraform_lock_enabled(team.id):
        return
    raise exceptions.PermissionDenied(LOCKED_RULE_MESSAGE)


def stamp_manager(request: Request | None, validated_data: dict[str, Any]) -> None:
    """Record the manager on a rule it just wrote, so later edits can be refused."""
    manager = request_manager(request)
    if manager is None:
        return
    validated_data["managed_by"] = manager
    validated_data["managed_at"] = now()


def team_has_managed_rules(team_id: int) -> bool:
    return AccessControl.objects.filter(team_id=team_id, managed_by__isnull=False).exists()


class AccessControlManagementSerializer(serializers.Serializer):
    """Addresses one rule the same way the unique constraint does, minus the team."""

    resource = serializers.CharField(help_text="Resource type the rule applies to, for example `dashboard`.")
    resource_id = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Specific object the rule applies to. Omit for a resource-wide rule.",
    )
    role = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Role the rule targets. Mutually exclusive with `organization_member`.",
    )
    organization_member = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Organization member the rule targets. Mutually exclusive with `role`.",
    )
    managed_by = serializers.ChoiceField(
        choices=AccessControlManager.choices,
        allow_null=True,
        help_text="Manager claiming the rule. Send null to release it, which makes the rule editable again.",
    )

    def validate_resource(self, resource: str) -> str:
        if resource not in API_SCOPE_OBJECTS or resource in INTERNAL_API_SCOPE_OBJECTS:
            raise serializers.ValidationError("Invalid resource.")
        return resource

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("role") and data.get("organization_member"):
            raise serializers.ValidationError("A rule cannot target both a member and a role.")
        return data


class AccessControlManagementStateSerializer(serializers.Serializer):
    managed_by = serializers.CharField(allow_null=True, help_text="Manager that owns the rule, or null.")
    managed_at = serializers.DateTimeField(allow_null=True, help_text="When the manager last claimed the rule.")


class AccessControlManagementSettingsSerializer(serializers.Serializer):
    lock_terraform_managed_rules = serializers.BooleanField(
        help_text="When on, only Terraform can change the rules that Terraform manages."
    )
    has_terraform_managed_rules = serializers.BooleanField(
        read_only=True,
        help_text="Whether any rule in this project is currently managed by Terraform.",
    )


class AccessControlManagementViewSetMixin(_GenericViewSet):
    """Mounted on the team and project viewsets only, next to AccessControlSettingsViewSetMixin.

    It is deliberately not on AccessControlViewSetMixin: that one is mixed into every product
    viewset, and these routes are project-scoped, so mounting there would register them 40+ times.
    """

    def dangerously_get_required_scopes(self, request, view) -> list[str] | None:
        if self.action == "access_control_management":
            return ["access_control:write"]
        if self.action == "access_control_management_settings":
            return ["access_control:read"] if request.method == "GET" else ["access_control:write"]
        parent = getattr(super(), "dangerously_get_required_scopes", None)
        return parent(request, view) if parent is not None else None

    def _assert_can_manage(self, team: Team) -> None:
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore[attr-defined]
        if not user_access_control.check_can_modify_access_levels_for_object(team):
            raise exceptions.PermissionDenied("Must be an Organization admin to manage access control ownership.")

    @extend_schema(exclude=True)
    @action(methods=["PUT"], detail=True, url_path="access_control_management")
    def access_control_management(self, request: Request, *args, **kwargs) -> Response:
        """Claim one existing rule for a manager, or release it.

        Terraform calls this while refreshing, so a rule it owns but never has to write still
        gets stamped. Releasing is the way back out: `terraform state rm` leaves a stamped rule
        with nothing managing it, and without a release it would stay locked forever.
        """
        team = cast(Team, self.team)  # type: ignore[attr-defined]
        self._assert_can_manage(team)

        serializer = AccessControlManagementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        instance = AccessControl.objects.filter(
            team=team,
            resource=params["resource"],
            resource_id=params["resource_id"],
            role=params["role"],
            organization_member=params["organization_member"],
        ).first()
        if instance is None:
            raise exceptions.NotFound("No access control rule matches that target.")

        # Releasing someone else's claim from a third party would be a way around the lock
        assert_rule_is_editable(request=request, team=team, instance=instance)

        instance.managed_by = params["managed_by"]
        instance.managed_at = now() if params["managed_by"] else None
        instance.save(update_fields=["managed_by", "managed_at"])

        return Response(AccessControlManagementStateSerializer(instance).data)

    @extend_schema(exclude=True)
    @action(methods=["GET", "PATCH"], detail=True, url_path="access_control_management_settings")
    def access_control_management_settings(self, request: Request, *args, **kwargs) -> Response:
        team = cast(Team, self.team)  # type: ignore[attr-defined]

        if request.method == "PATCH":
            self._assert_can_manage(team)
            serializer = AccessControlManagementSettingsSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            config = get_or_create_team_extension(team, TeamAccessControlConfig)
            config.lock_terraform_managed_rules = serializer.validated_data["lock_terraform_managed_rules"]
            config.save(update_fields=["lock_terraform_managed_rules"])
        else:
            config = get_or_create_team_extension(team, TeamAccessControlConfig)

        return Response(
            {
                "lock_terraform_managed_rules": config.lock_terraform_managed_rules,
                "has_terraform_managed_rules": team_has_managed_rules(team.id),
            }
        )


def role_has_locked_rules(organization_id: str, role_id: str) -> bool:
    """Whether deleting this role would take locked rules down with it.

    AccessControl.role cascades, so deleting a role removes its rules without any access control
    endpoint running. Without this check the lock is one role deletion away from being bypassed.
    A role is organization-scoped and its rules are per team, so every locked team counts.
    """
    locked_team_ids = TeamAccessControlConfig.objects.filter(
        lock_terraform_managed_rules=True, team__organization_id=organization_id
    ).values_list("team_id", flat=True)
    return AccessControl.objects.filter(team_id__in=locked_team_ids, role_id=role_id, managed_by__isnull=False).exists()

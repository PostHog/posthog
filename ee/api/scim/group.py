from django.db import transaction

from django_scim import constants
from django_scim.adapters import SCIMGroup

from posthog.models import OrganizationMembership, User
from posthog.models.organization_domain import OrganizationDomain

from ee.models.rbac.role import Role, RoleMembership


class PostHogSCIMGroup(SCIMGroup):
    """
    Adapter to map SCIM Group schema to PostHog RBAC Role model.
    SCIM Groups are mapped to PostHog Roles for organization-level permissions.
    """

    resource_type = "Group"

    @property
    def id(self) -> str:
        return str(self.obj.id)

    @property
    def display_name(self) -> str:
        return self.obj.name

    @property
    def members(self) -> list[dict]:
        """
        Return list of group members in SCIM format.
        """
        role_memberships = RoleMembership.objects.filter(role=self.obj).select_related("user")
        return [
            {
                "value": str(rm.user.id),
                "$ref": f"/scim/v2/{self._organization_domain.id}/Users/{rm.user.id}",
                "display": rm.user.email,
            }
            for rm in role_memberships
        ]

    def __init__(self, obj: Role, organization_domain: OrganizationDomain):
        super().__init__(obj)
        self._organization_domain = organization_domain

    @classmethod
    def resource_type_dict(cls, request=None) -> dict:
        return {
            "id": cls.resource_type,
            "name": cls.resource_type,
            "endpoint": f"/scim/v2/{request.auth.id if request and request.auth else '{domain_id}'}/Groups",
            "schema": constants.SchemaURI.GROUP,
        }

    def to_dict(self) -> dict:
        """
        Convert Role to SCIM Group format.
        """
        return {
            "id": self.id,
            "displayName": self.display_name,
            "members": self.members,
            "meta": {
                "resourceType": self.resource_type,
                "location": f"/scim/v2/{self._organization_domain.id}/Groups/{self.id}",
            },
        }

    @classmethod
    def from_dict(cls, data: dict, organization_domain: OrganizationDomain) -> "PostHogSCIMGroup":
        """
        Create or update a Role from SCIM Group data.
        Upserts role by name matching.
        """
        display_name = data.get("displayName")
        if not display_name:
            raise ValueError("displayName is required for groups")

        with transaction.atomic():
            # Upsert role by name
            role, created = Role.objects.get_or_create(
                name=display_name,
                organization=organization_domain.organization,
                defaults={"created_by": None},
            )

            # Handle member updates if provided
            if "members" in data:
                cls._update_members(role, data["members"], organization_domain)

        return cls(role, organization_domain)

    @classmethod
    def _update_members(cls, role: Role, members_data: list[dict], organization_domain: OrganizationDomain) -> None:
        """
        Update role membership based on SCIM members list.
        """
        # Get list of user IDs from SCIM data
        member_user_ids = {member.get("value") for member in members_data if member.get("value")}

        # Get current role members
        current_memberships = RoleMembership.objects.filter(role=role).select_related("user", "organization_member")

        current_user_ids = {str(rm.user.id) for rm in current_memberships}

        # Users to add
        to_add = member_user_ids - current_user_ids

        # Users to remove
        to_remove = current_user_ids - member_user_ids

        # Add new members
        for user_id in to_add:
            try:
                user = User.objects.get(id=user_id)
                org_membership = OrganizationMembership.objects.filter(
                    user=user, organization=organization_domain.organization
                ).first()

                if org_membership:
                    RoleMembership.objects.get_or_create(
                        role=role, user=user, defaults={"organization_member": org_membership}
                    )
            except User.DoesNotExist:
                continue

        # Remove members no longer in the group
        RoleMembership.objects.filter(role=role, user__id__in=to_remove).delete()

    def replace(self, data: dict) -> None:
        """
        Replace role from SCIM Group data (for PUT operations).
        """
        display_name = data.get("displayName")
        if not display_name:
            raise ValueError("displayName is required for groups")

        with transaction.atomic():
            if display_name != self.obj.name:
                self.obj.name = display_name
                self.obj.save()

            if "members" in data:
                self._update_members(self.obj, data["members"], self._organization_domain)

    def delete(self) -> None:
        """
        Delete the role.
        """
        self.obj.delete()

    def update(self, data: dict) -> None:
        """
        Update group from SCIM PATCH operation.
        Applies partial updates to specific group attributes.
        """
        if "displayName" in data:
            self.obj.name = data["displayName"]
            self.obj.save()

        if "members" in data:
            self._update_members(self.obj, data["members"], self._organization_domain)

    @classmethod
    def get_for_organization(cls, organization_domain: OrganizationDomain) -> list["PostHogSCIMGroup"]:
        """
        Get all roles (groups) for a specific organization.
        """
        roles = Role.objects.filter(organization=organization_domain.organization)
        return [cls(role, organization_domain) for role in roles]

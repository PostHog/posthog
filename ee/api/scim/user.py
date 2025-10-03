from typing import Optional

from django.db import transaction
from django_scim import constants
from django_scim.adapters import SCIMUser

from posthog.models import OrganizationMembership, User
from posthog.models.organization_domain import OrganizationDomain


class PostHogSCIMUser(SCIMUser):
    """
    Adapter to map SCIM User schema to PostHog User model.
    Handles user provisioning scoped to a specific OrganizationDomain.
    """

    resource_type = "User"

    @property
    def id(self) -> str:
        return str(self.obj.id)

    @property
    def display_name(self) -> Optional[str]:
        full_name = f"{self.obj.first_name} {self.obj.last_name}".strip()
        return full_name if full_name else None

    @property
    def emails(self) -> list[dict]:
        return [{"value": self.obj.email, "primary": True}]

    @property
    def name(self) -> dict:
        return {"givenName": self.obj.first_name or "", "familyName": self.obj.last_name or ""}

    @property
    def user_name(self) -> str:
        return self.obj.email

    @property
    def active(self) -> bool:
        # A user is "active" in SCIM context if they have membership in this org
        if not hasattr(self, "_organization_domain"):
            return self.obj.is_active
        return OrganizationMembership.objects.filter(
            user=self.obj, organization=self._organization_domain.organization
        ).exists()

    def __init__(self, obj: User, organization_domain: OrganizationDomain):
        super().__init__(obj)
        self._organization_domain = organization_domain

    @classmethod
    def resource_type_dict(cls, request=None) -> dict:
        return {
            "id": cls.resource_type,
            "name": cls.resource_type,
            "endpoint": f"/scim/v2/{request.auth.id if request and request.auth else '{domain_id}'}/Users",
            "schema": constants.SchemaURI.USER,
        }

    def to_dict(self) -> dict:
        """
        Convert User to SCIM format.
        """
        base_dict = {
            "id": self.id,
            "userName": self.user_name,
            "name": self.name,
            "emails": self.emails,
            "active": self.active,
            "meta": {
                "resourceType": self.resource_type,
                "location": f"/scim/v2/{self._organization_domain.id}/Users/{self.id}",
            },
        }

        if self.display_name:
            base_dict["displayName"] = self.display_name

        return base_dict

    @classmethod
    def from_dict(cls, d: dict, organization_domain: OrganizationDomain) -> "PostHogSCIMUser":
        """
        Create or update a User from SCIM data.
        """
        email = d.get("userName") or d.get("emails", [{}])[0].get("value")
        if not email:
            raise ValueError("userName or email is required")

        name_data = d.get("name", {})
        first_name = name_data.get("givenName", "")
        last_name = name_data.get("familyName", "")

        with transaction.atomic():
            # Try to find existing user by email
            user = User.objects.filter(email__iexact=email).first()

            if user:
                # Update existing user
                if first_name:
                    user.first_name = first_name
                if last_name:
                    user.last_name = last_name
                user.save()
            else:
                # Create new user with no password (they'll use SAML)
                user = User.objects.create_user(
                    email=email, password=None, first_name=first_name, last_name=last_name, is_email_verified=True
                )

            # Ensure user has membership in this organization
            membership, created = OrganizationMembership.objects.get_or_create(
                user=user,
                organization=organization_domain.organization,
                defaults={"level": OrganizationMembership.Level.MEMBER},
            )

            # Set current org/team if this is their first org
            if not user.current_organization:
                user.current_organization = organization_domain.organization
                user.current_team = organization_domain.organization.teams.first()
                user.save()

        return cls(user, organization_domain)

    def delete(self) -> None:
        """
        Deactivate user by removing their membership from this organization.
        """
        OrganizationMembership.objects.filter(
            user=self.obj, organization=self._organization_domain.organization
        ).delete()

    def handle_replace(self, data: dict) -> None:
        """
        Handle SCIM PATCH replace operations.
        """
        if "active" in data and not data["active"]:
            # If active=false, remove membership
            self.delete()
        else:
            # Update user attributes
            name_data = data.get("name", {})
            if "givenName" in name_data:
                self.obj.first_name = name_data["givenName"]
            if "familyName" in name_data:
                self.obj.last_name = name_data["familyName"]

            if "emails" in data and data["emails"]:
                self.obj.email = data["emails"][0]["value"]

            self.obj.save()

    @classmethod
    def get_for_organization(cls, organization_domain: OrganizationDomain) -> list["PostHogSCIMUser"]:
        """
        Get all users for a specific organization domain.
        """
        users = User.objects.filter(organization_membership__organization=organization_domain.organization)
        return [cls(user, organization_domain) for user in users]

from typing import Optional, Union

from django.db import transaction
from django.db.models import QuerySet

from django_scim import constants
from django_scim.adapters import SCIMUser
from scim2_filter_parser.attr_paths import AttrPath

from posthog.models import Organization, OrganizationMembership, User
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.organization_domain import OrganizationDomain

from products.access_control.backend.models.role import RoleMembership

from ee.models.scim_provisioned_user import SCIMProvisionedUser


class SCIMUserConflict(Exception):
    """User is already SCIM-provisioned for this identity provider configuration."""


def _validate_email_domain_is_verified(email: str, organization: Organization) -> None:
    """Ensure email domain matches any verified domain for the organization. Prevents cross-tenant user adoption."""
    # The delivery domain is the segment after the LAST "@" — splitting on the first "@"
    # would let a multi-"@" address smuggle a verified-looking domain past this guard.
    email_domain = email.rsplit("@", 1)[-1].lower()
    verified_domains = set(
        OrganizationDomain.objects.filter(
            organization=organization,
            verified_at__isnull=False,
        ).values_list("domain", flat=True)
    )
    if email_domain not in {d.lower() for d in verified_domains}:
        raise ValueError(f"Email domain '{email_domain}' does not match any verified domain for this organization")


class PostHogSCIMUser(SCIMUser):
    """
    Adapter to map SCIM User schema to PostHog User model.
    Handles user provisioning scoped to a specific IdentityProviderConfig.
    """

    resource_type = "User"

    # Attribute map for SCIM PATCH operation path parsing
    # Maps SCIM attribute paths to SCIM JSON paths for PATCH operations
    # NOT for database filtering - see SCIM_USER_ATTR_MAP in views.py for that
    # Each key is a tuple of (attribute, sub-attribute, schema URI)
    ATTR_MAP = {
        ("userName", None, None): "userName",
        ("name", "givenName", None): "name.givenName",
        ("name", "familyName", None): "name.familyName",
        ("emails", None, None): "emails",
        ("emails", "value", None): "emails.value",
        ("emails", "type", None): "emails.type",
        ("emails", "primary", None): "emails.primary",
        ("active", None, None): "active",
    }

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
        scim_user = SCIMProvisionedUser.objects.record_for(user=self.obj, config=self._config)
        return scim_user.username if scim_user else self.obj.email

    @property
    def identity_provider(self) -> str:
        scim_user = SCIMProvisionedUser.objects.record_for(user=self.obj, config=self._config)
        return scim_user.identity_provider if scim_user else SCIMProvisionedUser.IdentityProvider.OTHER

    @property
    def active(self) -> bool:
        # A user is "active" in SCIM context if they have membership in this org
        if not hasattr(self, "_config"):
            return self.obj.is_active
        return OrganizationMembership.objects.filter(user=self.obj, organization=self._config.organization).exists()

    def __init__(self, obj: User, config: IdentityProviderConfig):
        super().__init__(obj)
        self._config = config

    @staticmethod
    def _extract_email_from_value(emails: list[dict]) -> Optional[str]:
        """
        Extract email from SCIM emails array.
        Returns primary email if available, otherwise first email.
        """
        if not emails:
            return None
        primary_email = next((e["value"] for e in emails if e.get("primary")), None)
        return primary_email or emails[0]["value"]

    @classmethod
    def resource_type_dict(cls, request=None) -> dict:
        return {
            "id": cls.resource_type,
            "name": cls.resource_type,
            "endpoint": f"/scim/v2/{request.auth.scim_slug if request and request.auth else '{scim_slug}'}/Users",
            "schema": constants.SchemaURI.USER,
        }

    def to_dict(self) -> dict:
        """
        Convert User to SCIM format.
        """
        base_dict = {
            "schemas": [constants.SchemaURI.USER],
            "id": self.id,
            "userName": self.user_name,
            "name": self.name,
            "emails": self.emails,
            "active": self.active,
            "meta": {
                "resourceType": self.resource_type,
                "location": f"/scim/v2/{self._config.scim_slug}/Users/{self.id}",
            },
        }

        if self.display_name:
            base_dict["displayName"] = self.display_name

        role_memberships = RoleMembership.objects.filter(
            user=self.obj, role__organization=self._config.organization
        ).select_related("role")
        base_dict["groups"] = [
            {
                "value": str(rm.role.id),
                "$ref": f"/scim/v2/{self._config.scim_slug}/Groups/{rm.role.id}",
                "display": rm.role.name,
            }
            for rm in role_memberships
        ]

        return base_dict

    @classmethod
    def from_dict(
        cls,
        data: dict,
        config: IdentityProviderConfig,
        identity_provider: SCIMProvisionedUser.IdentityProvider = SCIMProvisionedUser.IdentityProvider.OTHER,
    ) -> "PostHogSCIMUser":
        """
        Create or update a User from SCIM data.
        """
        email = cls._extract_email_from_value(data.get("emails", []))
        if not email:
            raise ValueError("email is required")

        name_data = data.get("name", {})
        first_name = name_data.get("givenName", "")
        last_name = name_data.get("familyName", "")
        user_name = data.get("userName", email)
        active = data.get("active", True)

        with transaction.atomic():
            user = User.objects.filter(email__iexact=email).first()

            # Check if already SCIM-provisioned for this IdP config
            if user and SCIMProvisionedUser.objects.record_for(user=user, config=config) is not None:
                raise SCIMUserConflict()

            if user:
                is_member = OrganizationMembership.objects.filter(user=user, organization=config.organization).exists()
                if not is_member:
                    _validate_email_domain_is_verified(email, config.organization)

                if first_name:
                    user.first_name = first_name
                if last_name:
                    user.last_name = last_name
                user.save()
            else:
                _validate_email_domain_is_verified(email, config.organization)
                # Create new user with no password (they'll use SAML)
                user = User.objects.create_user(
                    email=email, password=None, first_name=first_name, last_name=last_name, is_email_verified=True
                )

            # Ensure user has membership in this organization
            OrganizationMembership.objects.get_or_create(
                user=user,
                organization=config.organization,
                defaults={"level": OrganizationMembership.Level.MEMBER},
            )

            # Set current org/team if this is their first org
            if not user.current_organization:
                user.current_organization = config.organization
                user.current_team = config.organization.teams.first()
                user.save()

            SCIMProvisionedUser.objects.upsert(
                user=user,
                config=config,
                defaults={
                    "identity_provider": identity_provider,
                    "username": user_name,
                    "active": active,
                },
            )

        return cls(user, config)

    def put(self, data: dict) -> None:
        """
        Handle SCIM PUT operation, completely replace user.

        Any attributes not provided are cleared.
        """
        name_data = data.get("name", {})
        email = self._extract_email_from_value(data.get("emails", []))
        user_name = data.get("userName", email)
        is_active = data.get("active", True)

        if not email:
            raise ValueError("Email is required")

        with transaction.atomic():
            # Do not allow changing email to another user's email
            existing_user_with_email = User.objects.filter(email__iexact=email).exclude(id=self.obj.id).first()
            if existing_user_with_email:
                raise ValueError("Email belongs to another user")

            _validate_email_domain_is_verified(email, self._config.organization)
            # Org must also own the current email domain to prevent cross-tenant account takeover
            _validate_email_domain_is_verified(self.obj.email, self._config.organization)

            self.obj.first_name = name_data.get("givenName", "")
            self.obj.last_name = name_data.get("familyName", "")
            self.obj.email = email
            self.obj.save()

            SCIMProvisionedUser.objects.upsert(
                user=self.obj,
                config=self._config,
                defaults={
                    "username": user_name,
                    "active": is_active,
                    "identity_provider": self.identity_provider,
                },
            )

            if is_active:
                # Adding org membership to reactivate the user
                OrganizationMembership.objects.get_or_create(
                    user=self.obj,
                    organization=self._config.organization,
                    defaults={"level": OrganizationMembership.Level.MEMBER},
                )
            else:
                self.deactivate()

    def _leave_organization(self) -> None:
        # Route membership removal through User.leave so the owner-protection guard and the
        # canonical current-org/team cleanup run. Tolerate an already-removed membership so
        # deprovisioning stays idempotent.
        try:
            self.obj.leave(organization=self._config.organization)
        except OrganizationMembership.DoesNotExist:
            pass

    def deactivate(self) -> None:
        """
        Deactivate user by removing their membership and marking SCIM record as inactive.
        """
        self._leave_organization()

        SCIMProvisionedUser.objects.for_config(self._config).filter(user=self.obj).update(active=False)

    def delete(self) -> None:
        """
        Delete user by removing their membership and SCIM provisioned user record.
        """
        self._leave_organization()

        SCIMProvisionedUser.objects.for_config(self._config).filter(user=self.obj).delete()

    def _activate(self) -> None:
        """Give the user back their organization membership and mark the SCIM record active."""
        OrganizationMembership.objects.get_or_create(
            user=self.obj,
            organization=self._config.organization,
            defaults={"level": OrganizationMembership.Level.MEMBER},
        )
        SCIMProvisionedUser.objects.upsert(
            user=self.obj,
            config=self._config,
            defaults={
                "active": True,
                "username": self.user_name,
                "identity_provider": self.identity_provider,
            },
        )

    def _set_username(self, username: str) -> None:
        SCIMProvisionedUser.objects.upsert(
            user=self.obj,
            config=self._config,
            defaults={
                "username": username,
                "active": True,
                "identity_provider": self.identity_provider,
            },
        )

    def _apply_name(self, sub_attr: Optional[str], value: Union[str, list, dict]) -> None:
        if sub_attr == "givenName" and isinstance(value, str):
            self.obj.first_name = value
        elif sub_attr == "familyName" and isinstance(value, str):
            self.obj.last_name = value
        elif isinstance(value, dict):
            if "givenName" in value:
                self.obj.first_name = value["givenName"]
            if "familyName" in value:
                self.obj.last_name = value["familyName"]

    def _clear_name(self, sub_attr: Optional[str]) -> None:
        if sub_attr == "givenName":
            self.obj.first_name = ""
        elif sub_attr == "familyName":
            self.obj.last_name = ""
        elif not sub_attr:
            self.obj.first_name = ""
            self.obj.last_name = ""

    @classmethod
    def _email_from_operation(cls, path: AttrPath, value: Union[str, list, dict]) -> Optional[str]:
        """Read the target email out of a PATCH value, which is a bare string for a filtered path."""
        if path.is_complex and isinstance(value, str):
            return value
        if isinstance(value, list):
            return cls._extract_email_from_value(value)
        return None

    def _apply_email(self, email: str) -> None:
        if User.objects.filter(email__iexact=email).exclude(id=self.obj.id).exists():
            raise ValueError("Email belongs to another user")
        _validate_email_domain_is_verified(email, self._config.organization)
        # Org must also own the current email domain to prevent cross-tenant account takeover
        _validate_email_domain_is_verified(self.obj.email, self._config.organization)
        self.obj.email = email

    def _write_attribute(self, path: AttrPath, value: Union[str, list, dict]) -> bool:
        """
        Write one SCIM attribute. Returns True when the User row still needs a save.

        Unknown attributes are ignored, because the SCIM spec lets a provider support a subset.
        """
        first_path = path.first_path
        attr_name = first_path.attr_name

        if attr_name == "active":
            if value:
                self._activate()
            else:
                self.deactivate()
            return False

        if attr_name == "name":
            self._apply_name(first_path.sub_attr, value)
            return True

        if attr_name == "emails":
            email = self._email_from_operation(path, value)
            if not email:
                return False
            self._apply_email(email)
            return True

        if attr_name == "userName" and isinstance(value, str):
            self._set_username(value)

        return False

    def _handle_write(self, path: AttrPath, value: Union[str, list, dict]) -> None:
        with transaction.atomic():
            if self._write_attribute(path, value):
                self.obj.save()

    def handle_replace(self, path: AttrPath, value: Union[str, list, dict], operation: dict) -> None:
        """
        Handle SCIM PATCH replace operations (called by django-scim2 handle_operations).

        Each attribute update comes as a separate call with its specific path and value.
        Supports complex paths like 'emails[type eq "work"].value' via scim2-filter-parser.
        """
        self._handle_write(path, value)

    def handle_add(self, path: AttrPath, value: Union[str, list, dict], operation: dict) -> None:
        """
        Handle SCIM PATCH add operations (called by django-scim2 handle_operations).

        A SCIM single-valued attribute has one slot, so an add on one behaves as a replace.
        """
        self._handle_write(path, value)

    def handle_remove(self, path: AttrPath, value: Union[str, list, dict], operation: dict) -> None:
        """
        Handle SCIM PATCH remove operations (called by django-scim2 handle_operations).
        """
        first_path = path.first_path
        attr_name = first_path.attr_name

        with transaction.atomic():
            if attr_name == "active":
                self.deactivate()

            elif attr_name == "name":
                self._clear_name(first_path.sub_attr)
                self.obj.save()

            elif attr_name == "emails":
                raise ValueError("Email is required and cannot be removed")

    @classmethod
    def get_queryset_for_organization(cls, config: IdentityProviderConfig) -> QuerySet[User]:
        return User.objects.filter(organization_membership__organization=config.organization).order_by("id")

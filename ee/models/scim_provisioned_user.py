from django.db import models

from posthog.models.utils import UpdatedMetaFields, UUIDModel


class SCIMProvisionedUser(UUIDModel, UpdatedMetaFields):
    class IdentityProvider(models.TextChoices):
        OKTA = "okta", "Okta"
        ENTRA_ID = "entra_id", "Microsoft Entra ID"
        GOOGLE = "google", "Google Workspace"
        ONELOGIN = "onelogin", "OneLogin"
        OTHER = "other", "Other"

    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="scim_provisions")
    organization_domain = models.ForeignKey(
        "posthog.OrganizationDomain", on_delete=models.CASCADE, related_name="scim_provisioned_users"
    )

    identity_provider = models.CharField(max_length=50, choices=IdentityProvider.choices)
    username = models.CharField(max_length=255)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization_domain"],
                name="unique_user_organization_domain",
            )
        ]
        indexes = [
            models.Index(fields=["organization_domain", "username"]),
        ]

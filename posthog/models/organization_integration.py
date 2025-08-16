from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.integration import Integration
from posthog.models.organization import Organization


class OrganizationIntegration(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    kind = models.CharField(max_length=50, choices=Integration.IntegrationKind.choices)
    integration_id = models.TextField(null=True, blank=True)
    config = models.JSONField(default=dict)
    sensitive_config = EncryptedJSONField(
        default=dict,
        ignore_decrypt_errors=True,  # allows us to load previously unencrypted data
    )

    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind", "integration_id"],
                name="posthog_organization_integration_kind_id_unique",
            )
        ]

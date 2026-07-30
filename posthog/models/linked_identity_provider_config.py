from django.db import models


class LinkedIdentityProviderConfig(models.Model):
    organization_domain = models.ForeignKey(
        "posthog.OrganizationDomain", on_delete=models.CASCADE, related_name="linked_identity_provider_configs"
    )
    identity_provider_config = models.ForeignKey(
        "posthog.IdentityProviderConfig", on_delete=models.CASCADE, related_name="linked_identity_provider_configs"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization_domain", "identity_provider_config"),
                name="unique_linked_identity_provider_config",
            )
        ]

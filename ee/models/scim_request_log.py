from django.db import models

from posthog.models.utils import UUIDModel

SCIM_REQUEST_LOG_RETENTION_DAYS = 180


class SCIMRequestLog(UUIDModel):
    # The `IdentityProviderConfig` the request authenticated against — the SCIM tenant.
    identity_provider_config = models.ForeignKey(
        "posthog.IdentityProviderConfig",
        on_delete=models.CASCADE,
        related_name="scim_request_logs",
        null=True,
        blank=True,
        db_index=False,
    )
    # Legacy tenant key, still read by the per-domain log listing so admins keep seeing requests
    # logged before SCIM moved onto the config. Don't write it: a SCIM request names a config, and a
    # config can back several domains.
    organization_domain = models.ForeignKey(
        "posthog.OrganizationDomain",
        on_delete=models.CASCADE,
        related_name="scim_request_logs",
        null=True,
        blank=True,
    )

    request_method = models.CharField(max_length=10)
    request_path = models.CharField(max_length=512)
    request_headers = models.JSONField(default=dict)
    request_body = models.JSONField(null=True, blank=True)

    response_status = models.SmallIntegerField()
    response_body = models.JSONField(null=True, blank=True)

    identity_provider = models.CharField(max_length=20)
    duration_ms = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization_domain", "-created_at"]),
            models.Index(fields=["identity_provider_config", "-created_at"]),
        ]
        ordering = ["-created_at", "-id"]

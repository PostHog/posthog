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
    # Legacy tenant key. Don't write it: a SCIM request names a config, and a config can back
    # several domains. Rows logged before the move are attributed to their config by the
    # `backfill_scim_request_log_config` command, which runs outside the deploy because this table
    # is large; until it has, the per-domain log listing reads this column so no history is hidden.
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

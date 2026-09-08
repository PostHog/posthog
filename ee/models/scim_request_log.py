from django.db import models

from posthog.models.utils import UUIDModel

SCIM_REQUEST_LOG_RETENTION_DAYS = 180


class SCIMRequestLog(UUIDModel):
    # The `IdentityProviderConfig` the request authenticated against — the SCIM tenant. Deleting a
    # config must not erase the record of what its IdP did to org memberships, which is the artifact
    # an investigation after an IdP or admin-session compromise starts from, so the row outlives it
    # and ages out on the retention window instead. It drops out of the per-domain listing at that
    # point: with the config gone there is no domain left to list it under.
    identity_provider_config = models.ForeignKey(
        "posthog.IdentityProviderConfig",
        on_delete=models.SET_NULL,
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

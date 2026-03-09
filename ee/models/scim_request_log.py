from django.db import models

from posthog.models.utils import UUIDModel

SCIM_REQUEST_LOG_RETENTION_DAYS = 180


class SCIMRequestLog(UUIDModel):
    organization_domain = models.ForeignKey(
        "posthog.OrganizationDomain",
        on_delete=models.CASCADE,
        related_name="scim_request_logs",
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
        ]
        ordering = ["-created_at", "-id"]

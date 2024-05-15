from django.db import models
from posthog.models import Organization
from posthog.models.utils import UUIDModel


class ProxyRecord(UUIDModel):
    organization: models.ForeignKey = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="proxy_records"
    )
    domain: models.CharField = models.CharField(max_length=64, unique=True)
    dns_records: models.JSONField = models.JSONField(null=True, blank=True)

    status: models.JSONField = models.JSONField(null=True, blank=True)

    class Status(models.TextChoices):
        WAITING = "waiting"
        PROVISIONING = "provisioning"
        VALID = "valid"
        REMOVED = "removed"

    status = models.CharField(
        choices=Status.choices,
        default=Status.WAITING,
    )

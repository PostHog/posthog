from django.db import models

from posthog.models import Organization
from posthog.models.utils import UUIDTModel


class ProxyRecord(UUIDTModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="proxy_records")
    domain = models.CharField(max_length=64, unique=True)
    target_cname = models.CharField(max_length=256, null=False)
    message = models.CharField(max_length=1024, null=True)

    class Status(models.TextChoices):
        WAITING = "waiting"
        ISSUING = "issuing"
        VALID = "valid"
        WARNING = "warning"
        ERRORING = "erroring"
        DELETING = "deleting"
        TIMED_OUT = "timed_out"

    status = models.CharField(
        choices=Status.choices,
        default=Status.WAITING,
    )

    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

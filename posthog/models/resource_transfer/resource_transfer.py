from django.db import models

from posthog.models.utils import UUIDTModel


class ResourceTransfer(UUIDTModel):
    # TODO: actually use this model
    source_team = models.ForeignKey("Team", on_delete=models.CASCADE)
    destination_team = models.ForeignKey("Team", on_delete=models.CASCADE)

    resource_kind = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100)

    created_at = models.DateTimeField(auto_now_add=True)
    last_transfered_at = models.DateTimeField(auto_now_add=True)

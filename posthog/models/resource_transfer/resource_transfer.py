from django.db import models

from posthog.models.utils import CreatedMetaFields, UUIDModel


class ResourceTransfer(CreatedMetaFields, UUIDModel):
    source_team = models.ForeignKey("Team", on_delete=models.CASCADE, related_name="outbound_resource_transfers")
    destination_team = models.ForeignKey("Team", on_delete=models.CASCADE, related_name="inbound_resource_transfers")

    resource_kind = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100)  # from the source team
    duplicated_resource_id = models.CharField(max_length=100)  # in the destination team

    last_transferred_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["resource_kind", "resource_id", "-last_transferred_at"],
                name="idx_restransfer_kind_id_time",
            ),
        ]

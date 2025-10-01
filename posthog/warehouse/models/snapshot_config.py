from django.db import models

from rest_framework import serializers

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDTModel


class DataWarehouseSnapshotConfig(CreatedMetaFields, UUIDTModel, DeletedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    saved_query = models.OneToOneField("posthog.DataWarehouseSavedQuery", on_delete=models.CASCADE)

    class Mode(models.TextChoices):
        CHECK = "check", "check"

    class SyncFrequency(models.TextChoices):
        NEVER = "never", "Never"
        DAILY = "day", "Daily"
        WEEKLY = "week", "Weekly"
        MONTHLY = "month", "Monthly"

    mode = models.CharField(max_length=255, choices=Mode.choices, default=Mode.CHECK)
    fields = models.JSONField(default=list)
    timestamp_field = models.CharField(max_length=255, null=True, blank=True)
    frequency = models.CharField(max_length=255, choices=SyncFrequency.choices, default=SyncFrequency.NEVER)
    merge_key = models.CharField(max_length=255, null=True, blank=True)

    # default is md5 based partitioning right now
    partition_count = models.IntegerField(null=True, blank=True)


class DataWarehouseSnapshotConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataWarehouseSnapshotConfig
        fields = ["mode", "fields", "timestamp_field", "frequency", "merge_key", "partition_count"]

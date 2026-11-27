from django.db import models

from rest_framework import serializers

from products.ai_observability.backend.api.dataset_serializers import StrictDatasetSerializer


class DatasetRetentionKind(models.TextChoices):
    DATASETS = "datasets", "Datasets"
    REVISIONS = "revisions", "Older revisions"


class DatasetRetentionQuerySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=DatasetRetentionKind.choices,
        default=DatasetRetentionKind.DATASETS,
        help_text="Whether to return expiring datasets or older revisions. Counts always include both.",
    )
    limit = serializers.IntegerField(
        default=5, min_value=1, max_value=50, help_text="Maximum entries to return, up to 50."
    )
    offset = serializers.IntegerField(default=0, min_value=0, help_text="Number of expiring entries to skip.")


class DatasetRetentionEntrySerializer(serializers.Serializer):
    dataset_id = serializers.UUIDField(read_only=True, help_text="Dataset to open or extend.")
    dataset_name = serializers.CharField(read_only=True, help_text="Name of the dataset.")
    dataset_archived = serializers.BooleanField(read_only=True, help_text="Whether the dataset is archived.")
    revision = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="Historical revision number, or null for a dataset."
    )
    expires_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="Earliest cleanup time if this dataset or revision remains unused."
    )


class DatasetRetentionReadSerializer(serializers.Serializer):
    datasets_count = serializers.IntegerField(
        read_only=True, help_text="Accessible active and archived datasets within seven days of expiry."
    )
    revisions_count = serializers.IntegerField(
        read_only=True,
        help_text="Accessible older revisions within seven days of expiry, excluding the latest revision.",
    )
    count = serializers.IntegerField(read_only=True, help_text="Total expiring entries of the requested kind.")
    results = DatasetRetentionEntrySerializer(
        many=True, read_only=True, help_text="Expiring entries, ordered by earliest cleanup time."
    )


class DatasetExtendRetentionSerializer(StrictDatasetSerializer):
    revision = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Revision to extend along with its dataset. Omit to extend only the dataset.",
    )

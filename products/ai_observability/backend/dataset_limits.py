from django.db import models


class DatasetConflictResponseResource(models.TextChoices):
    DATASETS = "datasets"
    DATASET_ITEMS = "dataset_items"
    DATASET_ITEM_VERSIONS = "dataset_item_versions"
    PROJECT_DATASET_ITEM_VERSIONS = "project_dataset_item_versions"


MAX_DATASET_EXPORT_MEGABYTES = 250
MAX_DATASET_EXPORT_BYTES = MAX_DATASET_EXPORT_MEGABYTES * 1_000_000

MAX_ITEMS_PER_DATASET = 2_000
MAX_DATASET_ITEM_PAYLOAD_BYTES = 406_666

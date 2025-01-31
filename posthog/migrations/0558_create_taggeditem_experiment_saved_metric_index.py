# Created manually
from django.db import migrations
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import models


class Migration(migrations.Migration):
    atomic = False  # Required for concurrent index operations

    dependencies = [
        ("posthog", "0557_remove_taggeditem_exactly_one_related_object_and_more"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="taggeditem",
            index=models.Index(
                fields=["experiment_saved_metric"],
                name="posthog_taggeditem_experiment_saved_metric_id_b6af2199",
            ),
        ),
        AddIndexConcurrently(
            model_name="taggeditem",
            index=models.Index(
                fields=["tag", "experiment_saved_metric"],
                name="unique_experiment_saved_metric_tagged_item",
                condition=models.Q(experiment_saved_metric__isnull=False),
            ),
        ),
    ]

from django.db import migrations
from django.contrib.postgres.operations import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0557_add_tags_to_experiment_saved_metrics"),
    ]

    operations = [
        ValidateConstraint(
            model_name="taggeditem",
            name="exactly_one_related_object",
        ),
    ]

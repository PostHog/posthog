from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1115_featureflag_filters_groups_default"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="hogfunction",
            index=models.Index(
                fields=["template_id"],
                name="hog_func_active_template_idx",
                condition=models.Q(deleted=False, enabled=True, template_id__isnull=False),
            ),
        ),
    ]

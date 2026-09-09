from django.conf import settings
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("ee", "0062_squash_2026_09_07_schema_addons"),
        ("event_definitions", "0011_propertydefinition_feature_flag_idx"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="enterpriseeventdefinition",
            index=models.Index(
                condition=models.Q(("hidden", True)),
                fields=["eventdefinition_ptr"],
                name="ee_event_definition_hidden",
            ),
        ),
    ]

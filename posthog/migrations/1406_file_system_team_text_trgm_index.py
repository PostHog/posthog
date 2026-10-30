import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.contrib.postgres.operations import BtreeGinExtension
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1405_user_onboarding_skipped_reason_connector"),
    ]

    operations = [
        BtreeGinExtension(),
        SafeAddIndexConcurrently(
            model_name="filesystem",
            index=django.contrib.postgres.indexes.GinIndex(
                models.F("team_id"),
                django.contrib.postgres.indexes.OpClass(
                    django.db.models.functions.text.Lower(
                        django.db.models.functions.text.Concat(
                            models.F("path"),
                            models.Value(" "),
                            models.F("type"),
                            output_field=models.TextField(),
                        )
                    ),
                    name="gin_trgm_ops",
                ),
                name="posthog_fs_team_text_trgm",
            ),
        ),
    ]

from django.conf import settings
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("batch_exports", "0006_alter_batchexport_team_and_more"),
        ("cdp", "0005_repair_hogfunction_batch_export_id_index"),
        ("posthog", "1374_teamheatmapconfig_capture_enforcement_started_at_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="hogfunction",
            index=models.Index(
                condition=models.Q(("deleted", False), ("enabled", True)),
                fields=["template_id"],
                name="hogfunction_active_template",
            ),
        ),
    ]

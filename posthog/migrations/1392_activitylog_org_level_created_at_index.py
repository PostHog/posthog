from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1391_organization_provisioning"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                condition=models.Q(("team_id__isnull", True)),
                fields=["organization_id", "-created_at"],
                name="idx_alog_org_level_created_at",
            ),
        ),
    ]

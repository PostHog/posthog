from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("posthog", "1392_organization_member_notice")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="organization",
            index=models.Index(fields=["updated_at"], name="posthog_org_updated_at_idx"),
        ),
    ]

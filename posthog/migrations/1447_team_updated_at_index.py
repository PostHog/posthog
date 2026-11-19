from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1446_organizationprovisioning_partner_paid_since"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="team",
            index=models.Index(fields=["updated_at"], name="posthog_team_updated_at_idx"),
        ),
    ]

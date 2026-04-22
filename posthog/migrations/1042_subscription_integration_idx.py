from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1041_backfill_subscription_integration"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="subscription",
            index=models.Index(fields=["integration"], name="posthog_sub_integration_idx"),
        ),
    ]

from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction, and PostHog policy keeps
    # concurrent index builds in their own migration away from regular DDL.
    atomic = False
    dependencies = [("posthog", "1235_userintegration_slack_kind")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="userintegration",
            index=models.Index(fields=["kind", "integration_id"], name="user_integration_kind_extid"),
        ),
    ]

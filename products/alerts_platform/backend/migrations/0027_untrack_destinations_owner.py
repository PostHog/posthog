from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0026_alert_destination_keeps_legacy_webhook_body"),
    ]

    operations = [
        # Phase 1 of retiring the column: it leaves model state and stays in Postgres, so pods on
        # either release keep querying the table. Its NOT NULL constraint has a database default,
        # so inserts that no longer name it still succeed. A later migration drops it.
        untrack_field("platformalertconfiguration", "destinations_owner"),
    ]

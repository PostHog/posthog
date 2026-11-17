from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0026_alert_destination_keeps_legacy_webhook_body"),
    ]

    # The column is NOT NULL with a database default, so inserts that no longer name it still succeed.
    operations = [
        untrack_field("platformalertconfiguration", "destinations_owner"),
    ]

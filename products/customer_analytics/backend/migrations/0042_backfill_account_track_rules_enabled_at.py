from django.db import migrations
from django.utils import timezone


def backfill_account_track_rules_enabled_at(apps, schema_editor):
    TeamCustomerAnalyticsConfig = apps.get_model("customer_analytics", "TeamCustomerAnalyticsConfig")
    TeamCustomerAnalyticsConfig.objects.using(schema_editor.connection.alias).filter(
        account_track_rules__enabled=True,
        account_track_rules_enabled_at__isnull=True,
    ).update(account_track_rules_enabled_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0041_account_track_rules_enabled_at"),
    ]

    operations = [
        migrations.RunPython(backfill_account_track_rules_enabled_at, migrations.RunPython.noop),
    ]

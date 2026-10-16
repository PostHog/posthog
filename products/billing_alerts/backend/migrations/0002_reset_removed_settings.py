from decimal import Decimal

from django.db import migrations
from django.db.models import Q


def reset_removed_settings(apps, schema_editor):
    # The API and editor no longer expose these three fields, so a stored non-default value would
    # keep changing billing's own evaluation with no way for its owner to see or clear it.
    BillingAlertConfiguration = apps.get_model("billing_alerts", "BillingAlertConfiguration")
    BillingAlertConfiguration.objects.filter(
        ~Q(minimum_value=Decimal("0")) | ~Q(evaluation_delay_hours=6) | ~Q(cooldown_hours=24)
    ).update(minimum_value=Decimal("0"), evaluation_delay_hours=6, cooldown_hours=24)


class Migration(migrations.Migration):
    dependencies = [
        ("billing_alerts", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.RunPython(reset_removed_settings, migrations.RunPython.noop, elidable=True),
    ]

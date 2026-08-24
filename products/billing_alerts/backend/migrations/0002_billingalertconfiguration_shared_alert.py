# Hand-written: nullable OneToOne link to the shared alert identity from
# the explicit-alert-ownership RFC. The DB constraint lands after backfill in
# a later phase.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing_alerts", "0001_initial"),
        ("alerts", "0004_shared_alert_identity_and_destination"),
    ]

    operations = [
        migrations.AddField(
            model_name="billingalertconfiguration",
            name="shared_alert",
            field=models.OneToOneField(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="billing_configuration",
                to="alerts.alertsharedidentity",
            ),
        ),
    ]

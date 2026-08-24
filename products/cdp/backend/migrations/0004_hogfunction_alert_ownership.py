# Hand-written: alert-ownership columns and constraints on HogFunction from the
# explicit-alert-ownership RFC. The owning side holds no DB constraint yet
# (`db_constraint=False` on the shared-alert FKs); constraints land after
# backfill in a later phase, so nothing here scans existing rows at write time.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cdp", "0003_hog_function_drafts"),
        ("alerts", "0004_shared_alert_identity_and_destination"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogfunction",
            name="alert_destination",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="executors",
                to="alerts.alertdestination",
            ),
        ),
        migrations.AddField(
            model_name="hogfunction",
            name="alert_event_kind",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddConstraint(
            model_name="hogfunction",
            constraint=models.UniqueConstraint(
                condition=models.Q(alert_destination__isnull=False),
                fields=["alert_destination", "alert_event_kind"],
                name="hogfunction_alert_destination_kind_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="hogfunction",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(alert_destination__isnull=True, alert_event_kind__isnull=True),
                    models.Q(
                        alert_destination__isnull=False,
                        alert_event_kind__isnull=False,
                        type="internal_destination",
                    ),
                    _connector="OR",
                ),
                name="hogfunction_alert_ownership_shape",
            ),
        ),
    ]

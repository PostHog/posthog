# Hand-written: adds the shared alert identity and destination models from the
# explicit-alert-ownership RFC. FKs into hot tables are constraint-free on create
# and added back NOT VALID afterwards; the remaining constraints get real DB
# constraints because their parents are small product tables.

import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0003_alter_alertconfiguration_calculation_interval"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlertSharedIdentity",
            fields=[
                (
                    "id",
                    models.UUIDField(default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("product", models.CharField(choices=[("insight", "Insight"), ("logs", "Logs"), ("billing", "Billing")], max_length=16)),
                (
                    "created_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="posthog.user"),
                ),
                (
                    "organization",
                    models.ForeignKey(db_constraint=False, on_delete=django.db.models.deletion.CASCADE, related_name="shared_alerts", to="posthog.organization"),
                ),
                (
                    "execution_team",
                    models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="shared_alerts", to="posthog.team"),
                ),
            ],
            options={
                "db_table": "alerts_sharedalert",
            },
        ),
        migrations.CreateModel(
            name="AlertDestination",
            fields=[
                (
                    "id",
                    models.UUIDField(default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "type",
                    models.CharField(choices=[("slack", "Slack"), ("discord", "Discord"), ("webhook", "Webhook"), ("teams", "Microsoft Teams")], max_length=16),
                ),
                ("name", models.CharField(blank=True, max_length=400)),
                (
                    "created_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="posthog.user"),
                ),
                (
                    "shared_alert",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="destinations", to="alerts.alertsharedidentity"),
                ),
            ],
            options={
                "db_table": "alerts_alertdestination",
            },
        ),
        migrations.AddField(
            model_name="alertconfiguration",
            name="shared_alert",
            field=models.OneToOneField(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="insight_configuration",
                to="alerts.alertsharedidentity",
            ),
        ),
    ]

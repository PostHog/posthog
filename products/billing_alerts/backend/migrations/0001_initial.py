# Generated manually for additive billing alert tables.

from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("posthog", "1238_ducklakebackfill_earliest_event_date"),
    ]

    operations = [
        migrations.CreateModel(
            name="BillingAlertConfiguration",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("organization_id", models.UUIDField(db_index=True)),
                (
                    "team",
                    models.ForeignKey(
                        db_column="execution_team_id",
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
                ("created_by_id", models.BigIntegerField(blank=True, null=True)),
                ("updated_by_id", models.BigIntegerField(blank=True, null=True)),
                ("name", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True)),
                ("enabled", models.BooleanField(default=True)),
                (
                    "metric",
                    models.CharField(choices=[("spend", "Spend"), ("usage", "Usage")], default="spend", max_length=20),
                ),
                ("currency", models.CharField(default="USD", max_length=3)),
                (
                    "threshold_type",
                    models.CharField(
                        choices=[
                            ("relative_increase", "Relative increase"),
                            ("absolute_value", "Absolute value"),
                            ("absolute_increase", "Absolute increase"),
                        ],
                        default="relative_increase",
                        max_length=32,
                    ),
                ),
                ("threshold_percentage", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("threshold_value", models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ("minimum_value", models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=20)),
                ("baseline_window_days", models.PositiveSmallIntegerField(default=7)),
                ("evaluation_delay_hours", models.PositiveSmallIntegerField(default=6)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("not_firing", "Not firing"),
                            ("firing", "Firing"),
                            ("errored", "Errored"),
                            ("snoozed", "Snoozed"),
                            ("broken", "Broken"),
                        ],
                        default="not_firing",
                        max_length=20,
                    ),
                ),
                ("check_interval_hours", models.PositiveSmallIntegerField(default=24)),
                ("cooldown_hours", models.PositiveSmallIntegerField(default=24)),
                ("snooze_until", models.DateTimeField(blank=True, null=True)),
                ("next_check_at", models.DateTimeField(blank=True, null=True)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_notified_at", models.DateTimeField(blank=True, null=True)),
                ("consecutive_failures", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, blank=True, null=True)),
            ],
            options={
                "db_table": "billing_alerts_configuration",
                "indexes": [
                    models.Index(fields=["organization_id", "-created_at"], name="billing_alert_org_created_idx"),
                    models.Index(fields=["enabled", "next_check_at"], name="billing_alert_scheduler_idx"),
                    models.Index(fields=["organization_id", "enabled", "state"], name="billing_alert_org_state_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="BillingAlertEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("check", "Check"),
                            ("firing", "Firing"),
                            ("resolved", "Resolved"),
                            ("errored", "Errored"),
                            ("broken_config", "Broken config"),
                        ],
                        default="check",
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("evaluation_date", models.DateField(blank=True, null=True)),
                ("period_start", models.DateTimeField(blank=True, null=True)),
                ("period_end", models.DateTimeField(blank=True, null=True)),
                (
                    "metric",
                    models.CharField(choices=[("spend", "Spend"), ("usage", "Usage")], max_length=20),
                ),
                ("current_value", models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ("baseline_value", models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ("absolute_delta", models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                (
                    "relative_delta_percentage",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True),
                ),
                (
                    "threshold_value_snapshot",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True),
                ),
                (
                    "threshold_percentage_snapshot",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
                ),
                (
                    "minimum_value_snapshot",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True),
                ),
                ("threshold_breached", models.BooleanField(default=False)),
                ("state_before", models.CharField(blank=True, max_length=20, null=True)),
                ("state_after", models.CharField(blank=True, max_length=20, null=True)),
                ("notification_sent_at", models.DateTimeField(blank=True, null=True)),
                ("targets_notified", models.JSONField(default=dict)),
                ("query_duration_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=80, null=True)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("is_transient_error", models.BooleanField(default=False)),
                ("reason", models.TextField(blank=True)),
                ("payload", models.JSONField(default=dict)),
                (
                    "alert",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="billing_alerts.billingalertconfiguration",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "billing_alerts_event",
                "indexes": [
                    models.Index(fields=["team", "-created_at"], name="billing_event_team_ts_idx"),
                    models.Index(fields=["alert", "-created_at"], name="billing_event_alert_ts_idx"),
                    models.Index(fields=["alert", "evaluation_date"], name="billing_event_alert_date_idx"),
                    models.Index(fields=["kind", "-created_at"], name="billing_event_kind_ts_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="billingalertevent",
            constraint=models.UniqueConstraint(
                condition=models.Q(evaluation_date__isnull=False, kind="check"),
                fields=("alert", "kind", "evaluation_date"),
                name="unique_billing_alert_check_event_date",
            ),
        ),
    ]

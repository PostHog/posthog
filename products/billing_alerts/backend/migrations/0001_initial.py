# Generated manually for additive billing alert tables.

from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("posthog", "1256_userproductlist_default_reason"),
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
                (
                    "organization",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.organization",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        blank=True,
                        db_column="execution_team_id",
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("name", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True)),
                ("enabled", models.BooleanField(default=True)),
                (
                    "metric",
                    models.CharField(choices=[("spend", "Spend")], default="spend", max_length=20),
                ),
                ("currency", models.CharField(choices=[("USD", "USD")], default="USD", max_length=3)),
                ("configuration_revision", models.PositiveIntegerField(default=1)),
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
                ("cooldown_hours", models.PositiveSmallIntegerField(default=24)),
                ("snoozed_until", models.DateTimeField(blank=True, null=True)),
                ("next_check_at", models.DateTimeField(blank=True, null=True)),
                ("pending_evaluation_date", models.DateField(blank=True, null=True)),
                ("retry_attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_notified_at", models.DateTimeField(blank=True, null=True)),
                ("consecutive_failures", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, blank=True, null=True)),
            ],
            options={
                "db_table": "billing_alerts_configuration",
                "indexes": [
                    models.Index(fields=["organization", "-created_at"], name="billing_alert_org_created_idx"),
                    models.Index(
                        models.F("enabled"),
                        models.OrderBy(models.F("next_check_at"), nulls_first=True),
                        name="billing_alert_scheduler_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("baseline_window_days__gte", 1)),
                        name="billing_alert_baseline_window_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("minimum_value__gte", 0)),
                        name="billing_alert_minimum_nonnegative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("threshold_percentage__gt", 0),
                            ("threshold_percentage__isnull", False),
                            ("threshold_type", "relative_increase"),
                        )
                        | models.Q(
                            ("threshold_type__in", ("absolute_value", "absolute_increase")),
                            ("threshold_value__gte", 0),
                            ("threshold_value__isnull", False),
                        ),
                        name="billing_alert_threshold_configuration_valid",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BillingAlertEvaluationClaim",
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
                ("evaluation_date", models.DateField()),
                ("configuration_revision", models.PositiveIntegerField()),
                ("delivery_uuid", models.UUIDField(default=posthog.models.utils.uuid7, editable=False, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("evaluating", "Evaluating"),
                            ("retryable", "Retryable"),
                            ("completed", "Completed"),
                            ("superseded", "Superseded"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("next_retry_at", models.DateTimeField(blank=True, null=True)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "alert",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="evaluation_claims",
                        to="billing_alerts.billingalertconfiguration",
                    ),
                ),
            ],
            options={
                "db_table": "billing_alerts_evaluation_claim",
                "indexes": [
                    models.Index(fields=["status", "next_retry_at"], name="billing_claim_retry_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("alert", "evaluation_date", "configuration_revision"),
                        name="unique_billing_alert_evaluation_claim",
                    )
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
                ("source", models.CharField(choices=[("scheduled", "Scheduled"), ("manual", "Manual")], max_length=16)),
                ("attempt_number", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("period_start", models.DateTimeField(blank=True, null=True)),
                ("period_end", models.DateTimeField(blank=True, null=True)),
                (
                    "metric",
                    models.CharField(choices=[("spend", "Spend")], max_length=20),
                ),
                ("current_value", models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ("baseline_value", models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ("absolute_delta", models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                (
                    "relative_delta_percentage",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=28, null=True),
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
                (
                    "state_before",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("not_firing", "Not firing"),
                            ("firing", "Firing"),
                            ("errored", "Errored"),
                            ("snoozed", "Snoozed"),
                            ("broken", "Broken"),
                        ],
                        max_length=20,
                        null=True,
                    ),
                ),
                (
                    "state_after",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("not_firing", "Not firing"),
                            ("firing", "Firing"),
                            ("errored", "Errored"),
                            ("snoozed", "Snoozed"),
                            ("broken", "Broken"),
                        ],
                        max_length=20,
                        null=True,
                    ),
                ),
                ("notification_sent_at", models.DateTimeField(blank=True, null=True)),
                ("targets_notified", models.JSONField(default=dict)),
                ("query_duration_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=80, null=True)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("is_transient_error", models.BooleanField(default=False)),
                ("reason", models.TextField(blank=True)),
                ("payload", models.JSONField(default=dict)),
                (
                    "claim",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attempts",
                        to="billing_alerts.billingalertevaluationclaim",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "billing_alerts_event",
                "indexes": [
                    models.Index(fields=["team", "-created_at"], name="billing_event_team_ts_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="billingalertevent",
            constraint=models.UniqueConstraint(
                fields=("claim", "attempt_number"),
                name="unique_billing_alert_evaluation_attempt",
            ),
        ),
    ]

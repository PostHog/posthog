# Generated manually - Refactors CoreEvent from JSON field to proper table

import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0953_create_core_event"),
    ]

    operations = [
        # Drop old TeamCoreEventsConfig table (no data migration needed - no existing users)
        migrations.DeleteModel(
            name="TeamCoreEventsConfig",
        ),
        # Create new CoreEvent table
        migrations.CreateModel(
            name="CoreEvent",
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
                    "name",
                    models.CharField(
                        help_text="Display name for this core event",
                        max_length=255,
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Optional description",
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("acquisition", "Acquisition"),
                            ("activation", "Activation"),
                            ("monetization", "Monetization"),
                            ("expansion", "Expansion"),
                            ("referral", "Referral"),
                            ("retention", "Retention"),
                            ("churn", "Churn"),
                            ("reactivation", "Reactivation"),
                        ],
                        help_text="Category (acquisition, activation, retention, referral, revenue)",
                        max_length=20,
                    ),
                ),
                (
                    "filter",
                    models.JSONField(
                        help_text="Filter configuration - event, action, or data warehouse node",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="core_events",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "verbose_name": "Core Event",
                "verbose_name_plural": "Core Events",
                "ordering": ["created_at"],
            },
        ),
    ]

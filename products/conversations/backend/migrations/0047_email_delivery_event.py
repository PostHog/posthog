import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0046_ticket_org_id_indexes"),
        ("posthog", "1251_alter_integration_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailDeliveryEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("message_id", models.CharField(max_length=255)),
                ("recipient", models.CharField(max_length=254)),
                (
                    "event",
                    models.CharField(
                        choices=[
                            ("delivered", "Delivered"),
                            ("failed", "Failed"),
                            ("complained", "Complained"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        blank=True,
                        choices=[("permanent", "Permanent"), ("temporary", "Temporary")],
                        default="",
                        max_length=20,
                    ),
                ),
                ("reason", models.TextField(blank=True, default="")),
                ("provider_event_id", models.CharField(max_length=128, unique=True)),
                ("occurred_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "comment",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.comment"),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False, on_delete=django.db.models.deletion.CASCADE, to="posthog.team"
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="conversations.ticket"),
                ),
            ],
            options={
                "db_table": "posthog_conversations_email_delivery_event",
                "indexes": [
                    models.Index(fields=["team", "ticket", "-created_at"], name="posthog_con_delivery_tkt_idx")
                ],
            },
        ),
    ]

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1047_dashboard_quick_filter_ids"),
        ("conversations", "0023_ticket_sla_due_at_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamConversationsEmailConfig",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                ("inbound_token", models.CharField(max_length=64, unique=True, db_index=True)),
                ("from_email", models.EmailField(max_length=254)),
                ("from_name", models.CharField(max_length=255)),
                ("domain", models.CharField(max_length=255)),
                ("domain_verified", models.BooleanField(default=False)),
                ("dns_records", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "posthog_conversations_email_config",
            },
        ),
        migrations.CreateModel(
            name="EmailMessageMapping",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.CharField(max_length=255, unique=True, db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="conversations.ticket",
                    ),
                ),
                (
                    "comment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.comment",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_conversations_email_message_mapping",
            },
        ),
        migrations.AddIndex(
            model_name="emailmessagemapping",
            index=models.Index(fields=["team", "ticket"], name="conv_email_map_team_ticket_idx"),
        ),
    ]

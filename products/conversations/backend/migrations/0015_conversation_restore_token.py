import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1013_eventdefinition_enforcement_mode_db_default"),
        ("conversations", "0014_remove_ticket_assigned_to"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConversationRestoreToken",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                ("recipient_email", models.EmailField(max_length=254)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("consumed_by_widget_session_id", models.CharField(blank=True, max_length=64, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=models.CASCADE, related_name="conversation_restore_tokens", to="posthog.team"
                    ),
                ),
            ],
            options={
                "db_table": "posthog_conversations_restore_token",
            },
        ),
        migrations.AddIndex(
            model_name="conversationrestoretoken",
            index=models.Index(fields=["team", "recipient_email"], name="posthog_crt_team_email_idx"),
        ),
        migrations.AddIndex(
            model_name="conversationrestoretoken",
            index=models.Index(fields=["expires_at"], name="posthog_crt_expires_idx"),
        ),
    ]

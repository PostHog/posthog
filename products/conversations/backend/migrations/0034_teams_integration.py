from django.db import migrations, models

import posthog.helpers.encrypted_fields


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1094_oauth_provisioning_fields"),
        ("conversations", "0033_ticket_snoozed_until_idx"),
    ]

    operations = [
        # New model: TeamConversationsTeamsConfig
        migrations.CreateModel(
            name="TeamConversationsTeamsConfig",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                ("teams_tenant_id", models.CharField(blank=True, max_length=64, null=True)),
                (
                    "teams_graph_access_token",
                    posthog.helpers.encrypted_fields.EncryptedTextField(blank=True, max_length=4000, null=True),
                ),
                (
                    "teams_graph_refresh_token",
                    posthog.helpers.encrypted_fields.EncryptedTextField(blank=True, max_length=4000, null=True),
                ),
                ("teams_token_expires_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "posthog_conversations_teams_config",
            },
        ),
        migrations.AddIndex(
            model_name="teamconversationsteamsconfig",
            index=models.Index(fields=["teams_tenant_id"], name="conv_teams_cfg_tenant_id_idx"),
        ),
        migrations.AddConstraint(
            model_name="teamconversationsteamsconfig",
            constraint=models.UniqueConstraint(
                condition=models.Q(("teams_tenant_id__isnull", False)),
                fields=("teams_tenant_id",),
                name="unique_teams_tenant_id",
            ),
        ),
        # Add Teams fields to Ticket (all nullable, safe to add)
        migrations.AddField(
            model_name="ticket",
            name="teams_channel_id",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="teams_conversation_id",
            field=models.CharField(blank=True, max_length=256, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="teams_service_url",
            field=models.URLField(blank=True, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="teams_tenant_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        # Update choices in Django state (no DB change for CharField choices)
        migrations.AlterField(
            model_name="ticket",
            name="channel_detail",
            field=models.CharField(
                blank=True,
                choices=[
                    ("slack_channel_message", "Channel message"),
                    ("slack_bot_mention", "Bot mention"),
                    ("slack_emoji_reaction", "Emoji reaction"),
                    ("teams_channel_message", "Teams channel message"),
                    ("teams_bot_mention", "Teams bot mention"),
                    ("widget_embedded", "Widget"),
                    ("widget_api", "API"),
                ],
                max_length=30,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="ticket",
            name="channel_source",
            field=models.CharField(
                choices=[
                    ("widget", "Widget"),
                    ("email", "Email"),
                    ("slack", "Slack"),
                    ("teams", "Microsoft Teams"),
                ],
                default="widget",
                max_length=20,
            ),
        ),
        # Ticket index is in 0032 (AddIndexConcurrently requires atomic=False)
    ]

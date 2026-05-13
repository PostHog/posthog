import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0036_github_issues_channel"),
        ("posthog", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatChannel",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=80)),
                ("description", models.TextField(blank=True, default="")),
                ("is_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="chat_channels", to="posthog.team"
                    ),
                ),
            ],
            options={
                "db_table": "posthog_conversations_chat_channel",
            },
        ),
        migrations.AddIndex(
            model_name="chatchannel",
            index=models.Index(fields=["team", "name"], name="posthog_con_chat_chan_team_idx"),
        ),
        migrations.AddConstraint(
            model_name="chatchannel",
            constraint=models.UniqueConstraint(fields=("team", "name"), name="unique_chat_channel_name_per_team"),
        ),
        migrations.CreateModel(
            name="ChatChannelMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                (
                    "channel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="conversations.chatchannel",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chat_channel_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "posthog_conversations_chat_channel_membership",
            },
        ),
        migrations.AddConstraint(
            model_name="chatchannelmembership",
            constraint=models.UniqueConstraint(fields=("channel", "user"), name="unique_chat_channel_membership"),
        ),
    ]

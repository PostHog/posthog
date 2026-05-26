import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("agent_stack", "0002_drop_agent_application_session"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="IdentitySpace",
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
                ("name", models.CharField(max_length=63)),
                ("deleted", models.BooleanField(default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="identityspace",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted", False)),
                fields=("team", "name"),
                name="agent_stack_identityspace_unique_active_name",
            ),
        ),
        migrations.AddIndex(
            model_name="identityspace",
            index=models.Index(fields=["team", "deleted"], name="agent_stack_idspace_team"),
        ),
        migrations.CreateModel(
            name="AgentUser",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                (
                    "space",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="users",
                        to="agent_stack.identityspace",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="agentuser",
            index=models.Index(fields=["space", "-last_seen_at"], name="agent_stack_user_seen"),
        ),
        migrations.CreateModel(
            name="UserIdentity",
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
                ("provider", models.CharField(max_length=63)),
                ("provider_account_id", models.CharField(max_length=255)),
                ("provider_subject", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "space",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="identities",
                        to="agent_stack.identityspace",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="identities",
                        to="agent_stack.agentuser",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="useridentity",
            constraint=models.UniqueConstraint(
                fields=("space", "provider", "provider_account_id", "provider_subject"),
                name="agent_stack_useridentity_unique_tuple",
            ),
        ),
    ]

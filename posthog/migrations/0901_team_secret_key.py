# Generated manually

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0900_team_receive_org_level_activity_logs"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamSecretKey",
            fields=[
                (
                    "id",
                    models.CharField(
                        editable=False,
                        help_text="Short identifier for the secret key",
                        max_length=50,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(help_text="Descriptive name for this secret key", max_length=100)),
                ("mask_value", models.CharField(editable=False, max_length=20)),
                (
                    "secure_value",
                    models.CharField(
                        db_index=True,
                        editable=False,
                        help_text="SHA256 hash of the secret key",
                        max_length=300,
                        unique=True,
                    ),
                ),
                ("last_used_at", models.DateTimeField(blank=True, help_text="When this key was last used", null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_team_secret_keys",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="secret_keys",
                        to="posthog.team",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="teamsecretkey",
            constraint=models.UniqueConstraint(fields=("team", "name"), name="unique_team_secret_key_name"),
        ),
        migrations.AddIndex(
            model_name="teamsecretkey",
            index=models.Index(fields=["team", "created_at"], name="posthog_tea_team_id_1e37a1_idx"),
        ),
    ]

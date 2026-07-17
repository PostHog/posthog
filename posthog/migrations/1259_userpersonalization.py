import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils
from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("posthog", "1258_duckgressinkschemastate_queue_last_applied_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserPersonalization",
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
                    "avatar_url",
                    models.URLField(
                        blank=True,
                        help_text="Profile picture URL, shown across PostHog apps in place of the Gravatar/initials fallback.",
                        max_length=800,
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="personalization",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        AddForeignKeyNotValid(
            model_name="userpersonalization",
            name="posthog_userpersonalization_user_id_fk",
            column="user_id",
            to_table="posthog_user",
        ),
    ]

import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [("posthog", "1212_grandfather_stripe_provisioned_pat")]

    operations = [
        migrations.CreateModel(
            name="FileSystemFolderInstructions",
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
                ("content", models.TextField()),
                ("version", models.PositiveIntegerField(default=1)),
                ("is_latest", models.BooleanField(default=True)),
                ("deleted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "folder",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="instruction_versions",
                        to="posthog.filesystem",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="filesystemfolderinstructions",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted", False)),
                fields=("folder", "version"),
                name="unique_folder_instructions_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="filesystemfolderinstructions",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted", False), ("is_latest", True)),
                fields=("folder",),
                name="unique_folder_instructions_latest",
            ),
        ),
    ]

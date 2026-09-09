import django.db.models.manager
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils
from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0051_squash_2026_09_07_schema_addons"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AnnouncementTemplate",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("message", models.TextField()),
                ("deleted", models.BooleanField(default=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "abstract": False,
                "default_manager_name": "all_teams",
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddIndex(
            model_name="announcementtemplate",
            index=models.Index(fields=["team_id", "name"], name="ca_ann_template_team_idx"),
        ),
        migrations.AddConstraint(
            model_name="announcementtemplate",
            constraint=models.UniqueConstraint(
                condition=models.Q(deleted=False),
                fields=("team", "name"),
                name="ca_ann_template_uniq_name",
            ),
        ),
        AddForeignKeyNotValid(
            model_name="announcementtemplate",
            name="ca_ann_template_team_id_fk",
            column="team_id",
            to_table="posthog_team",
            to_column="id",
        ),
        AddForeignKeyNotValid(
            model_name="announcementtemplate",
            name="ca_ann_template_created_by_id_fk",
            column="created_by_id",
            to_table="posthog_user",
            to_column="id",
        ),
    ]

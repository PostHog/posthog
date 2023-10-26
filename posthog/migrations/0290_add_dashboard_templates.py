# Generated by Django 3.2.16 on 2023-01-14 15:25

import django.contrib.postgres.fields
import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0289_add_tags_to_feature_flags"),
    ]

    operations = [
        migrations.CreateModel(
            name="DashboardTemplate",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("template_name", models.CharField(max_length=400, null=True)),
                ("dashboard_description", models.CharField(max_length=400, null=True)),
                ("dashboard_filters", models.JSONField(null=True)),
                ("tiles", models.JSONField(default=list)),
                (
                    "tags",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=255),
                        default=list,
                        size=None,
                    ),
                ),
                ("github_url", models.CharField(max_length=8201, null=True)),
                (
                    "team",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="dashboardtemplate",
            constraint=models.UniqueConstraint(fields=("template_name", "team"), name="unique_template_name_per_team"),
        ),
    ]

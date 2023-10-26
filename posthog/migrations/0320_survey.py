# Generated by Django 3.2.18 on 2023-05-29 16:41

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0319_user_requested_password_reset_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="Survey",
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
                ("name", models.CharField(max_length=400)),
                ("description", models.TextField(blank=True)),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("popover", "popover"),
                            ("button", "button"),
                            ("email", "email"),
                            ("full_screen", "full screen"),
                        ],
                        max_length=40,
                    ),
                ),
                ("conditions", models.JSONField(blank=True, null=True)),
                ("questions", models.JSONField(blank=True, null=True)),
                ("appearance", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("start_date", models.DateTimeField(null=True)),
                ("end_date", models.DateTimeField(null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived", models.BooleanField(default=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="surveys",
                        related_query_name="survey",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "linked_flag",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="surveys_linked_flag",
                        related_query_name="survey",
                        to="posthog.featureflag",
                    ),
                ),
                (
                    "targeting_flag",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="surveys_targeting_flag",
                        related_query_name="survey",
                        to="posthog.featureflag",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="surveys",
                        related_query_name="survey",
                        to="posthog.team",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="survey",
            constraint=models.UniqueConstraint(fields=("team", "name"), name="unique survey name for team"),
        ),
    ]

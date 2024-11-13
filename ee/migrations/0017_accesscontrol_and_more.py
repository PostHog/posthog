# Generated by Django 4.2.15 on 2024-11-07 17:05

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0512_errortrackingissue_errortrackingissuefingerprintv2_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ee", "0016_rolemembership_organization_member"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccessControl",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("access_level", models.CharField(max_length=32)),
                ("resource", models.CharField(max_length=32)),
                ("resource_id", models.CharField(max_length=36, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "organization_member",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_controls",
                        related_query_name="access_controls",
                        to="posthog.organizationmembership",
                    ),
                ),
                (
                    "role",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_controls",
                        related_query_name="access_controls",
                        to="ee.role",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_controls",
                        related_query_name="access_controls",
                        to="posthog.team",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="accesscontrol",
            constraint=models.UniqueConstraint(
                fields=("resource", "resource_id", "team", "organization_member", "role"),
                name="unique resource per target",
            ),
        ),
    ]

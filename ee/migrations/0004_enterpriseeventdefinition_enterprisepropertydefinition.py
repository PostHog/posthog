# Generated by Django 3.1.8 on 2021-06-02 19:42

from django.conf import settings
import django.contrib.postgres.fields
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0156_insight_short_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ee", "0003_license_max_users"),
    ]

    operations = [
        migrations.CreateModel(
            name="EnterprisePropertyDefinition",
            fields=[
                (
                    "propertydefinition_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="posthog.propertydefinition",
                    ),
                ),
                ("description", models.CharField(blank=True, max_length=400)),
                (
                    "tags",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=32), blank=True, default=list, null=True, size=None
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
            options={"abstract": False,},
            bases=("posthog.propertydefinition",),
        ),
        migrations.CreateModel(
            name="EnterpriseEventDefinition",
            fields=[
                (
                    "eventdefinition_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="posthog.eventdefinition",
                    ),
                ),
                ("description", models.CharField(blank=True, max_length=400)),
                (
                    "tags",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=32), blank=True, default=list, null=True, size=None
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="event_definitions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
            options={"abstract": False,},
            bases=("posthog.eventdefinition",),
        ),
    ]

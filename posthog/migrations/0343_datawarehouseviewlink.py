# Generated by Django 3.2.19 on 2023-08-09 15:10

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0342_alter_featureflag_usage_dashboard"),
    ]

    operations = [
        migrations.CreateModel(
            name="DataWarehouseViewLink",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("deleted", models.BooleanField(blank=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("table", models.CharField(max_length=128)),
                ("from_join_key", models.CharField(max_length=400)),
                ("to_join_key", models.CharField(max_length=400)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "saved_query",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="posthog.datawarehousesavedquery"
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "abstract": False,
            },
        ),
    ]

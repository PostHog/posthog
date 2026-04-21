import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0897_migrate_data_warehouse_models"),
        ("data_warehouse", "0045_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalDataSourceProjectionRevision",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("version", models.PositiveIntegerField()),
                ("config", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.user",
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="projection_revisions",
                        to="data_warehouse.externaldatasource",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
                ),
            ],
            options={
                "db_table": "posthog_externaldatasourceprojectionrevision",
            },
        ),
        migrations.AddConstraint(
            model_name="externaldatasourceprojectionrevision",
            constraint=models.UniqueConstraint(
                fields=("source", "version"),
                name="posthog_externaldatasourceprojectionrevision_source_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldatasourceprojectionrevision",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("source",),
                name="posthog_externaldatasourceprojectionrevision_one_active_per_source",
            ),
        ),
    ]

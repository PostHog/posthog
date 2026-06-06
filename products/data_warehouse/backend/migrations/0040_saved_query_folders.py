import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0897_migrate_data_warehouse_models"),
        ("data_warehouse", "0039_add_parent_workflow_id_to_data_modeling_job"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DataWarehouseSavedQueryFolder",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
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
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "name",
                    models.CharField(
                        help_text="Display name for the folder used to organize saved queries in the SQL editor sidebar.",
                        max_length=128,
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "db_table": "posthog_datawarehousesavedqueryfolder",
            },
        ),
        migrations.AddConstraint(
            model_name="datawarehousesavedqueryfolder",
            constraint=models.UniqueConstraint(
                fields=("team", "name"),
                name="posthog_datawarehouse_saved_query_folder_unique_name",
            ),
        ),
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="folder",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional folder used to organize this saved query in the SQL editor sidebar.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="saved_queries",
                to="data_warehouse.datawarehousesavedqueryfolder",
            ),
        ),
    ]

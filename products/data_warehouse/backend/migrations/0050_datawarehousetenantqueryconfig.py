import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0049_externaldatasource_created_via"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DataWarehouseTenantQueryConfig",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, blank=True, null=True),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
                ("tenant_column_name", models.CharField(max_length=128)),
                (
                    "tenant_column_names_by_table",
                    models.JSONField(blank=True, default=dict, null=True),
                ),
                (
                    "tenant_column_type",
                    models.CharField(
                        choices=[("integer", "integer"), ("string", "string"), ("uuid", "uuid")],
                        max_length=32,
                    ),
                ),
                ("default_timeout_ms", models.PositiveIntegerField(default=30000)),
                ("max_timeout_ms", models.PositiveIntegerField(default=120000)),
                ("max_result_limit", models.PositiveIntegerField(default=100000)),
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
                    "external_data_source",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tenant_query_config",
                        to="data_warehouse.externaldatasource",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
                ),
            ],
            options={
                "db_table": "posthog_datawarehousetenantqueryconfig",
            },
        ),
    ]

from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0043_datawarehousesavedquery_query_revision"),
    ]

    operations = [
        migrations.AddField(
            model_name="node",
            name="metric_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="node",
            name="type",
            field=models.TextField(
                choices=[
                    ("table", "Table"),
                    ("view", "View"),
                    ("matview", "Mat View"),
                    ("endpoint", "Endpoint"),
                    ("metric", "Metric"),
                ],
                default="table",
                max_length=16,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="node",
            name="saved_query_required_on_non_table_node_type",
        ),
        AddConstraintNotValid(
            model_name="node",
            constraint=models.CheckConstraint(
                name="node_backing_reference_matches_type",
                condition=(
                    Q(type="table", metric_id__isnull=True)
                    | Q(
                        type__in=["endpoint", "matview", "view"],
                        saved_query__isnull=False,
                        metric_id__isnull=True,
                    )
                    | Q(type="metric", saved_query__isnull=True, metric_id__isnull=False)
                ),
            ),
        ),
    ]

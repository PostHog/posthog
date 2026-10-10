from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0046_dwsavedquery_team_live_created_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="node",
            name="insight_id",
            field=models.BigIntegerField(
                blank=True,
                help_text="ID of the insight an insight node stands for, or null for any other node.",
                null=True,
            ),
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
                    ("insight", "Insight"),
                ],
                default="table",
                max_length=16,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="node",
            name="node_backing_reference_matches_type",
        ),
        AddConstraintNotValid(
            model_name="node",
            constraint=models.CheckConstraint(
                name="node_backing_reference_matches_type",
                condition=(
                    Q(type="table", metric_id__isnull=True, insight_id__isnull=True)
                    | Q(
                        type__in=["endpoint", "matview", "view"],
                        saved_query__isnull=False,
                        metric_id__isnull=True,
                        insight_id__isnull=True,
                    )
                    | Q(type="metric", saved_query__isnull=True, metric_id__isnull=False, insight_id__isnull=True)
                    | Q(type="insight", saved_query__isnull=True, metric_id__isnull=True, insight_id__isnull=False)
                ),
            ),
        ),
    ]

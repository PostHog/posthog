from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers import CreateIndexConcurrently, DropIndexConcurrently, ValidateConstraint

NODE_TABLE = "posthog_datamodelingnode"


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0044_node_metric_type"),
    ]

    operations = [
        ValidateConstraint(model_name="node", name="node_backing_reference_matches_type"),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                CreateIndexConcurrently(
                    index_name="metric_unique_within_team_dag",
                    table_name=NODE_TABLE,
                    columns="(team_id, dag_fk_id, metric_id)",
                    unique=True,
                    where="WHERE metric_id IS NOT NULL",
                ),
                CreateIndexConcurrently(
                    index_name="name_unique_within_team_dag_for_tables_v2",
                    table_name=NODE_TABLE,
                    columns="(team_id, dag_fk_id, name)",
                    unique=True,
                    where="WHERE saved_query_id IS NULL AND metric_id IS NULL",
                ),
                DropIndexConcurrently(
                    index_name="name_unique_within_team_dag_for_tables",
                    table_name=NODE_TABLE,
                    columns="(team_id, dag_fk_id, name)",
                    unique=True,
                    where="WHERE saved_query_id IS NULL",
                ),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="node",
                    constraint=models.UniqueConstraint(
                        condition=Q(metric_id__isnull=False),
                        fields=["team", "dag", "metric_id"],
                        name="metric_unique_within_team_dag",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="node",
                    constraint=models.UniqueConstraint(
                        condition=Q(saved_query__isnull=True, metric_id__isnull=True),
                        fields=["team", "dag", "name"],
                        name="name_unique_within_team_dag_for_tables_v2",
                    ),
                ),
                migrations.RemoveConstraint(
                    model_name="node",
                    name="name_unique_within_team_dag_for_tables",
                ),
            ],
        ),
    ]

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0011_remove_edge_dag_id_column"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="node",
            name="saved_query_unique_within_team_dag",
        ),
        migrations.RemoveConstraint(
            model_name="node",
            name="name_unique_within_team_dag_for_tables",
        ),
    ]

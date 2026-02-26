from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0014_add_edge_dag_id_text_constraint"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="node",
            constraint=models.UniqueConstraint(
                condition=models.Q(("saved_query__isnull", False)),
                fields=("team", "dag_id_text", "saved_query"),
                name="saved_query_unique_within_team_dag_text",
            ),
        ),
        migrations.AddConstraint(
            model_name="node",
            constraint=models.UniqueConstraint(
                condition=models.Q(("saved_query__isnull", True)),
                fields=("team", "dag_id_text", "name"),
                name="name_unique_within_team_dag_text_for_tables",
            ),
        ),
    ]

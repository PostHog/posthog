from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0013_remove_node_dag_id_column"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="edge",
            constraint=models.UniqueConstraint(
                fields=("dag_id_text", "source", "target"),
                name="unique_within_dag_text",
            ),
        ),
    ]

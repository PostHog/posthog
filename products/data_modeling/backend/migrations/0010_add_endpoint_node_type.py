from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0009_edge_dag_id_text_node_dag_id_text"),
    ]

    operations = [
        migrations.AlterField(
            model_name="node",
            name="type",
            field=models.TextField(
                choices=[("table", "Table"), ("view", "View"), ("matview", "Mat View"), ("endpoint", "Endpoint")],
                default="table",
                max_length=16,
            ),
        ),
    ]

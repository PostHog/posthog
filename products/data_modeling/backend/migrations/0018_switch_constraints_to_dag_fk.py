import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0017_make_old_dag_text_fields_nullable"),
    ]

    operations = [
        # 1. Remove old unique constraints that reference the text dag_id column
        migrations.RemoveConstraint(
            model_name="node",
            name="saved_query_unique_within_team_dag",
        ),
        migrations.RemoveConstraint(
            model_name="node",
            name="name_unique_within_team_dag_for_tables",
        ),
        # 2. State-only: remove old text fields and rename dag_fk -> dag
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="node", name="dag_id"),
                migrations.RemoveField(model_name="node", name="dag_id_text"),
                migrations.RemoveField(model_name="edge", name="dag_id"),
                migrations.RemoveField(model_name="edge", name="dag_id_text"),
                migrations.RenameField(model_name="node", old_name="dag_fk", new_name="dag"),
                migrations.RenameField(model_name="edge", old_name="dag_fk", new_name="dag"),
                migrations.AlterField(
                    model_name="node",
                    name="dag",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="dag_fk_id",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="data_modeling.dag",
                    ),
                ),
                migrations.AlterField(
                    model_name="edge",
                    name="dag",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="dag_fk_id",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="data_modeling.dag",
                    ),
                ),
            ],
            database_operations=[],
        ),
        # 3. Add new unique constraints using the dag FK column (dag_fk_id)
        migrations.AddConstraint(
            model_name="node",
            constraint=models.UniqueConstraint(
                condition=models.Q(saved_query__isnull=False),
                fields=["team", "dag", "saved_query"],
                name="saved_query_unique_within_team_dag",
            ),
        ),
        migrations.AddConstraint(
            model_name="node",
            constraint=models.UniqueConstraint(
                condition=models.Q(saved_query__isnull=True),
                fields=["team", "dag", "name"],
                name="name_unique_within_team_dag_for_tables",
            ),
        ),
    ]

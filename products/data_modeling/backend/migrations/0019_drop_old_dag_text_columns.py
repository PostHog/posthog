from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0018_switch_constraints_to_dag_fk"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE posthog_datamodelingnode DROP COLUMN IF EXISTS dag_id, DROP COLUMN IF EXISTS dag_id_text;"
                    " ALTER TABLE posthog_datamodelingedge DROP COLUMN IF EXISTS dag_id, DROP COLUMN IF EXISTS dag_id_text;",
                    migrations.RunSQL.noop,
                ),
            ],
        ),
    ]

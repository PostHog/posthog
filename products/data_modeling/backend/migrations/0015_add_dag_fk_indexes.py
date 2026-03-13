from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0014_node_dag_fk"),
    ]

    operations = [
        migrations.RunSQL(
            sql='CREATE INDEX CONCURRENTLY IF NOT EXISTS "posthog_datamodelingedge_dag_fk_id_af85451c" ON "posthog_datamodelingedge" ("dag_fk_id");',
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "posthog_datamodelingedge_dag_fk_id_af85451c";',
        ),
        migrations.RunSQL(
            sql='CREATE INDEX CONCURRENTLY IF NOT EXISTS "posthog_datamodelingnode_dag_fk_id_a152d589" ON "posthog_datamodelingnode" ("dag_fk_id");',
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "posthog_datamodelingnode_dag_fk_id_a152d589";',
        ),
    ]

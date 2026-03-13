from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0016_backfill_dag_fks"),
    ]

    operations = [
        # Make old text columns nullable so inserts without them succeed after
        # migration 0018 removes them from Django state. These columns will be
        # fully dropped in a follow-up PR.
        migrations.RunSQL(
            "ALTER TABLE posthog_datamodelingnode ALTER COLUMN dag_id DROP NOT NULL, ALTER COLUMN dag_id_text DROP NOT NULL;"
            " ALTER TABLE posthog_datamodelingedge ALTER COLUMN dag_id DROP NOT NULL, ALTER COLUMN dag_id_text DROP NOT NULL;",
            "ALTER TABLE posthog_datamodelingnode ALTER COLUMN dag_id SET NOT NULL, ALTER COLUMN dag_id_text SET NOT NULL;"
            " ALTER TABLE posthog_datamodelingedge ALTER COLUMN dag_id SET NOT NULL, ALTER COLUMN dag_id_text SET NOT NULL;",
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0038_make_dataset_item_version_dataset_non_null"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="datasetitem",
            constraint=models.UniqueConstraint(
                fields=("id", "dataset", "team"),
                name="uniq_llma_dataset_item_v2_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="datasetrevision",
            constraint=models.UniqueConstraint(
                fields=("id", "dataset", "team"),
                name="uniq_llma_dataset_rev_v2_owner",
            ),
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE llm_analytics_datasetitemversion_v2
                ADD CONSTRAINT llma_item_ver_item_owner_fk
                FOREIGN KEY (dataset_item_id, dataset_id, team_id)
                REFERENCES llm_analytics_datasetitem_v2 (id, dataset_id, team_id)
                DEFERRABLE INITIALLY DEFERRED NOT VALID
            """,
            reverse_sql="""
                ALTER TABLE llm_analytics_datasetitemversion_v2
                DROP CONSTRAINT IF EXISTS llma_item_ver_item_owner_fk
            """,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE llm_analytics_datasetitemversion_v2
                ADD CONSTRAINT llma_item_ver_revision_owner_fk
                FOREIGN KEY (dataset_revision_id, dataset_id, team_id)
                REFERENCES llm_analytics_datasetrevision_v2 (id, dataset_id, team_id)
                DEFERRABLE INITIALLY DEFERRED NOT VALID
            """,
            reverse_sql="""
                ALTER TABLE llm_analytics_datasetitemversion_v2
                DROP CONSTRAINT IF EXISTS llma_item_ver_revision_owner_fk
            """,
        ),
    ]

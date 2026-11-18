from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0053_offline_evaluation_owner_uniqueness"),
    ]

    operations = [
        # Scorer writes lock versions before definitions; NOWAIT avoids a lock-order deadlock.
        migrations.RunSQL(
            sql="""
                SET LOCAL lock_timeout = '20s';
                LOCK TABLE
                    llm_analytics_scoredefinition,
                    llm_analytics_scoredefinitionversion,
                    llm_analytics_datasetrevision_v2,
                    llm_analytics_datasetitemversion_v2
                IN SHARE ROW EXCLUSIVE MODE NOWAIT;
                ALTER TABLE llm_analytics_offlineevaluationresult
                ADD CONSTRAINT aio_offline_result_scorer_owner_fk
                FOREIGN KEY (scorer_definition_id, team_id)
                REFERENCES llm_analytics_scoredefinition (id, team_id)
                DEFERRABLE INITIALLY DEFERRED NOT VALID
            """,
            reverse_sql="""
                ALTER TABLE llm_analytics_offlineevaluationresult
                DROP CONSTRAINT IF EXISTS aio_offline_result_scorer_owner_fk
            """,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE llm_analytics_offlineevaluationresult
                ADD CONSTRAINT aio_offline_result_scorer_version_fk
                FOREIGN KEY (scorer_version_id, scorer_definition_id)
                REFERENCES llm_analytics_scoredefinitionversion (id, definition_id)
                DEFERRABLE INITIALLY DEFERRED NOT VALID
            """,
            reverse_sql="""
                ALTER TABLE llm_analytics_offlineevaluationresult
                DROP CONSTRAINT IF EXISTS aio_offline_result_scorer_version_fk
            """,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE llm_analytics_offlineexperiment
                ADD CONSTRAINT aio_offline_exp_dataset_owner_fk
                FOREIGN KEY (dataset_revision_id, team_id)
                REFERENCES llm_analytics_datasetrevision_v2 (id, team_id)
                DEFERRABLE INITIALLY DEFERRED NOT VALID
            """,
            reverse_sql="""
                ALTER TABLE llm_analytics_offlineexperiment
                DROP CONSTRAINT IF EXISTS aio_offline_exp_dataset_owner_fk
            """,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE llm_analytics_offlineexperimentitem
                ADD CONSTRAINT aio_offline_item_dataset_owner_fk
                FOREIGN KEY (dataset_item_version_id, team_id)
                REFERENCES llm_analytics_datasetitemversion_v2 (id, team_id)
                DEFERRABLE INITIALLY DEFERRED NOT VALID
            """,
            reverse_sql="""
                ALTER TABLE llm_analytics_offlineexperimentitem
                DROP CONSTRAINT IF EXISTS aio_offline_item_dataset_owner_fk
            """,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE llm_analytics_offlineexperimentitem
                ADD CONSTRAINT aio_offline_item_experiment_fk
                FOREIGN KEY (experiment_id, team_id)
                REFERENCES llm_analytics_offlineexperiment (id, team_id)
                DEFERRABLE INITIALLY DEFERRED NOT VALID
            """,
            reverse_sql="""
                ALTER TABLE llm_analytics_offlineexperimentitem
                DROP CONSTRAINT IF EXISTS aio_offline_item_experiment_fk
            """,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE llm_analytics_offlineevaluationresult
                ADD CONSTRAINT aio_offline_result_item_fk
                FOREIGN KEY (item_id, team_id)
                REFERENCES llm_analytics_offlineexperimentitem (id, team_id)
                DEFERRABLE INITIALLY DEFERRED NOT VALID
            """,
            reverse_sql="""
                ALTER TABLE llm_analytics_offlineevaluationresult
                DROP CONSTRAINT IF EXISTS aio_offline_result_item_fk
            """,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE llm_analytics_offlineexperimentitempayload
                ADD CONSTRAINT aio_offline_item_payload_fk
                FOREIGN KEY (item_id, team_id)
                REFERENCES llm_analytics_offlineexperimentitem (id, team_id)
                DEFERRABLE INITIALLY DEFERRED NOT VALID
            """,
            reverse_sql="""
                ALTER TABLE llm_analytics_offlineexperimentitempayload
                DROP CONSTRAINT IF EXISTS aio_offline_item_payload_fk
            """,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE llm_analytics_offlineevaluationresultpayload
                ADD CONSTRAINT aio_offline_result_payload_fk
                FOREIGN KEY (result_id, team_id)
                REFERENCES llm_analytics_offlineevaluationresult (id, team_id)
                DEFERRABLE INITIALLY DEFERRED NOT VALID
            """,
            reverse_sql="""
                SET LOCAL lock_timeout = '20s';
                LOCK TABLE
                    llm_analytics_scoredefinition,
                    llm_analytics_scoredefinitionversion,
                    llm_analytics_datasetrevision_v2,
                    llm_analytics_datasetitemversion_v2
                IN SHARE ROW EXCLUSIVE MODE NOWAIT;
                ALTER TABLE llm_analytics_offlineevaluationresultpayload
                DROP CONSTRAINT IF EXISTS aio_offline_result_payload_fk
            """,
        ),
    ]

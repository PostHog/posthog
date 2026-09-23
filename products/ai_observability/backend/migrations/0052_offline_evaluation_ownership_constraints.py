from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0051_offline_evaluation_models"),
    ]

    operations = [
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
                ALTER TABLE llm_analytics_offlineevaluationresultpayload
                DROP CONSTRAINT IF EXISTS aio_offline_result_payload_fk
            """,
        ),
    ]

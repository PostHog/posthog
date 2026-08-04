from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1287_taggeditem_experiment"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS "posthog_taggeditem_experiment_id_idx"
                ON "posthog_taggeditem" ("experiment_id");
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS "posthog_taggeditem_experiment_id_idx";
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "unique_experiment_tagged_item"
                ON "posthog_taggeditem" ("tag_id", "experiment_id")
                WHERE "experiment_id" IS NOT NULL; -- not-null-ignore
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS "unique_experiment_tagged_item";
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_experiment_uniq"
                ON "posthog_taggeditem" (
                    "tag_id",
                    "dashboard_id",
                    "insight_id",
                    "event_definition_id",
                    "property_definition_id",
                    "action_id",
                    "feature_flag_id",
                    "experiment_saved_metric_id",
                    "ticket_id",
                    "account_id",
                    "endpoint_id",
                    "experiment_id"
                );
            """,
            reverse_sql="""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_endpoint_uniq"
                ON "posthog_taggeditem" (
                    "tag_id",
                    "dashboard_id",
                    "insight_id",
                    "event_definition_id",
                    "property_definition_id",
                    "action_id",
                    "feature_flag_id",
                    "experiment_saved_metric_id",
                    "ticket_id",
                    "account_id",
                    "endpoint_id"
                );
            """,
        ),
    ]

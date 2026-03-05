from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1032_remove_taggeditem_exactly_one_related_object_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS "posthog_taggeditem_ticket_id_idx"
                ON "posthog_taggeditem" ("ticket_id");
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS "posthog_taggeditem_ticket_id_idx";
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "unique_ticket_tagged_item"
                ON "posthog_taggeditem" ("tag_id", "ticket_id")
                WHERE "ticket_id" IS NOT NULL; -- not-null-ignore
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS "unique_ticket_tagged_item";
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_d90686d0_uniq"
                ON "posthog_taggeditem" (
                    "tag_id",
                    "dashboard_id",
                    "insight_id",
                    "event_definition_id",
                    "property_definition_id",
                    "action_id",
                    "feature_flag_id",
                    "experiment_saved_metric_id",
                    "ticket_id"
                );
            """,
            reverse_sql="""
                CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_734394e1_uniq"
                ON "posthog_taggeditem" (
                    "tag_id",
                    "dashboard_id",
                    "insight_id",
                    "event_definition_id",
                    "property_definition_id",
                    "action_id",
                    "feature_flag_id",
                    "experiment_saved_metric_id"
                );
            """,
        ),
    ]

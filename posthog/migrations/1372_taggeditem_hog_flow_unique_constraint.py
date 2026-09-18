from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1371_taggeditem_hog_flow_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE "posthog_taggeditem" ADD CONSTRAINT "posthog_taggeditem_tag_id_dashboard_id_insi_hog_flow_uniq"
                UNIQUE USING INDEX "posthog_taggeditem_tag_id_dashboard_id_insi_hog_flow_uniq"; -- existing-table-constraint-ignore
            """,
            # The reverse restores the experiment-wide constraint that 1370 dropped with a noop
            # reverse. It must build the index itself: this migration unapplies before 1371, so
            # nothing else has.
            reverse_sql="""
                ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_hog_flow_uniq";
                CREATE UNIQUE INDEX IF NOT EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_experiment_uniq"
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
                    "replay_scanner_id",
                    "project_id",
                    "experiment_id"
                );
                ALTER TABLE "posthog_taggeditem" ADD CONSTRAINT "posthog_taggeditem_tag_id_dashboard_id_insi_experiment_uniq"
                UNIQUE USING INDEX "posthog_taggeditem_tag_id_dashboard_id_insi_experiment_uniq"; -- existing-table-constraint-ignore
            """,
        ),
    ]

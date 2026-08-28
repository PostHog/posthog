from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("posthog", "1329_taggeditem_experiment_indexes")]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE "posthog_taggeditem" ADD CONSTRAINT "posthog_taggeditem_tag_id_dashboard_id_insi_experiment_uniq"
                UNIQUE USING INDEX "posthog_taggeditem_tag_id_dashboard_id_insi_experiment_uniq"; -- existing-table-constraint-ignore
            """,
            # The reverse restores the replay-scanner-wide constraint that 1328 dropped with a noop
            # reverse. It must build the index itself: this migration unapplies before 1329, so
            # nothing else has.
            reverse_sql="""
                ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_experiment_uniq";
                CREATE UNIQUE INDEX IF NOT EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_replay_scan_uniq"
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
                    "replay_scanner_id"
                );
                ALTER TABLE "posthog_taggeditem" ADD CONSTRAINT "posthog_taggeditem_tag_id_dashboard_id_insi_replay_scan_uniq"
                UNIQUE USING INDEX "posthog_taggeditem_tag_id_dashboard_id_insi_replay_scan_uniq"; -- existing-table-constraint-ignore
            """,
        ),
    ]

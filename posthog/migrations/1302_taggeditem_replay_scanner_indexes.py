from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1301_taggeditem_replay_scanner"),
    ]

    # `CreateIndexConcurrently` drops any invalid leftover from an interrupted build before
    # retrying, so a transient cancellation can't wedge 1303's ADD CONSTRAINT USING INDEX.
    # Django state for these indexes and constraints was added in 1301.
    operations = [
        CreateIndexConcurrently(
            index_name="posthog_taggeditem_replay_scanner_id_idx",
            table_name="posthog_taggeditem",
            columns='("replay_scanner_id")',
        ),
        CreateIndexConcurrently(
            index_name="unique_replay_scanner_tagged_item",
            table_name="posthog_taggeditem",
            columns='("tag_id", "replay_scanner_id")',
            unique=True,
            where='WHERE "replay_scanner_id" IS NOT NULL',
        ),
        CreateIndexConcurrently(
            index_name="posthog_taggeditem_tag_id_dashboard_id_insi_replay_scan_uniq",
            table_name="posthog_taggeditem",
            columns=(
                '("tag_id", "dashboard_id", "insight_id", "event_definition_id", "property_definition_id", '
                '"action_id", "feature_flag_id", "experiment_saved_metric_id", "ticket_id", "account_id", '
                '"endpoint_id", "replay_scanner_id")'
            ),
            unique=True,
        ),
    ]

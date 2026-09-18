from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1370_taggeditem_hog_flow"),
    ]

    # `CreateIndexConcurrently` drops any invalid leftover from an interrupted build before
    # retrying, so a transient cancellation can't wedge 1372's ADD CONSTRAINT USING INDEX.
    # Django state for these indexes and constraints was added in 1370.
    operations = [
        CreateIndexConcurrently(
            index_name="posthog_taggeditem_hog_flow_id_idx",
            table_name="posthog_taggeditem",
            columns='("hog_flow_id")',
        ),
        CreateIndexConcurrently(
            index_name="unique_hog_flow_tagged_item",
            table_name="posthog_taggeditem",
            columns='("tag_id", "hog_flow_id")',
            unique=True,
            where='WHERE "hog_flow_id" IS NOT NULL',
        ),
        CreateIndexConcurrently(
            index_name="posthog_taggeditem_tag_id_dashboard_id_insi_hog_flow_uniq",
            table_name="posthog_taggeditem",
            columns=(
                '("tag_id", "dashboard_id", "insight_id", "event_definition_id", "property_definition_id", '
                '"action_id", "feature_flag_id", "experiment_saved_metric_id", "ticket_id", "account_id", '
                '"endpoint_id", "replay_scanner_id", "project_id", "experiment_id", "hog_flow_id")'
            ),
            unique=True,
        ),
    ]

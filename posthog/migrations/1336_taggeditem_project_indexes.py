from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1335_taggeditem_project"),
    ]

    # `CreateIndexConcurrently` drops any invalid leftover from an interrupted build before
    # retrying, so a transient cancellation can't wedge 1337's ADD CONSTRAINT USING INDEX.
    # Django state for these indexes and constraints was added in 1335.
    operations = [
        CreateIndexConcurrently(
            index_name="posthog_taggeditem_project_id_0a61d235",
            table_name="posthog_taggeditem",
            columns='("project_id")',
        ),
        CreateIndexConcurrently(
            index_name="unique_project_tagged_item",
            table_name="posthog_taggeditem",
            columns='("tag_id", "project_id")',
            unique=True,
            where='WHERE "project_id" IS NOT NULL',
        ),
        CreateIndexConcurrently(
            index_name="posthog_taggeditem_tag_id_dashboard_id_insi_4ec15a8f_uniq",
            table_name="posthog_taggeditem",
            columns=(
                '("tag_id", "dashboard_id", "insight_id", "event_definition_id", "property_definition_id", '
                '"action_id", "feature_flag_id", "experiment_saved_metric_id", "ticket_id", "account_id", '
                '"endpoint_id", "replay_scanner_id", "project_id")'
            ),
            unique=True,
        ),
    ]

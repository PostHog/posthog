from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so the index builds don't block writes to posthog_taggeditem;
    # concurrent builds can't run in a transaction, hence atomic = False.
    # CreateIndexConcurrently disables timeouts, recovers invalid leftovers from
    # interrupted builds, and uses IF NOT EXISTS so bin/migrate retries are no-ops.
    atomic = False

    dependencies = [
        ("posthog", "1298_taggeditem_notebook"),
    ]

    operations = [
        CreateIndexConcurrently(
            index_name="posthog_taggeditem_notebook_id_idx",
            table_name="posthog_taggeditem",
            columns='("notebook_id")',
        ),
        CreateIndexConcurrently(
            index_name="unique_notebook_tagged_item",
            table_name="posthog_taggeditem",
            columns='("tag_id", "notebook_id")',
            unique=True,
            where='WHERE "notebook_id" IS NOT NULL',  # not-null-ignore
        ),
        CreateIndexConcurrently(
            index_name="posthog_taggeditem_tag_id_dashboard_id_insi_notebook_uniq",
            table_name="posthog_taggeditem",
            columns=(
                '("tag_id", "dashboard_id", "insight_id", "event_definition_id", "property_definition_id", '
                '"action_id", "feature_flag_id", "experiment_saved_metric_id", "ticket_id", "account_id", '
                '"endpoint_id", "notebook_id")'
            ),
            unique=True,
        ),
    ]

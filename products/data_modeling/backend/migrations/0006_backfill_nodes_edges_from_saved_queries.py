# manually created by andrewjmcgehee

# NOTE: this migration originally backfilled Node and Edge models from existing
# SavedQueries, but used direct model imports which broke when new fields were
# added to DataWarehouseSavedQuery. Since this backfill has already run in
# production and the migration is elidable, it has been converted to a no-op.

from django.db import migrations


def backfill_nodes_and_edges(apps, schema_editor):
    pass


def reverse_backfill(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0005_remove_node_name_unique_within_team_dag_and_more"),
        ("posthog", "0979_survey_enable_iframe_embedding"),  # included just to get the latest team/user migrations
    ]

    operations = [
        migrations.RunPython(backfill_nodes_and_edges, reverse_backfill, elidable=True),
    ]

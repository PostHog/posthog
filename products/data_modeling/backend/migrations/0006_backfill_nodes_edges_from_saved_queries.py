# manually created by andrewjmcgehee
# This was a one-off backfill that has already been applied in production.
# Replaced with a no-op to prevent breakage when the DataWarehouseSavedQuery model changes,
# since the original code used direct model imports instead of apps.get_model().

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0005_remove_node_name_unique_within_team_dag_and_more"),
        ("posthog", "0979_survey_enable_iframe_embedding"),
    ]

    operations = []

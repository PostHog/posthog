from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [("posthog", "1375_file_system_home_folder")]

    operations = [
        # Phase 1 of retiring the columns TeamExperimentsConfig superseded in #53674. The fields
        # leave model state while the columns stay, so pods on either release keep working.
        # posthog_team and posthog_organization are hot tables, so the DROP COLUMN follows in its
        # own migration one deploy cycle later.
        untrack_field(
            "team",
            "experiment_recalculation_time",
            "default_experiment_confidence_level",
            "default_experiment_stats_method",
        ),
        untrack_field("organization", "default_experiment_stats_method"),
    ]

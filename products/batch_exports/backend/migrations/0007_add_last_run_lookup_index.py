from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """Index the lookup of a batch export's latest completed run.

    Every batch export run reads the newest completed run of its parent to estimate how many
    staging files to write. `posthog_batchexportrun` carries only its primary key and its foreign
    key indexes, so that lookup reads the parent's whole run history and sorts it to find one row,
    and the cost grows with the history.

    The index leads with the parent and ends with `data_interval_end`, so the planner seeks to the
    parent and reads the newest run first, with no sort step. `posthog_batchexportrun` is large and
    written several times per run, so the index builds with CREATE INDEX CONCURRENTLY through
    SafeAddIndexConcurrently, which takes a SHARE UPDATE EXCLUSIVE lock and does not block reads or
    writes.
    """

    atomic = False

    dependencies = [
        ("batch_exports", "0006_alter_batchexport_team_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="batchexportrun",
            index=models.Index(
                fields=["batch_export", "-data_interval_end"],
                name="be_run_export_interval_idx",
            ),
        ),
    ]

from django.db import migrations, transaction

from posthog.migration_helpers.lock_phase import lock_tables

# One statement, so the table is locked once for a catalog change that rewrites no rows.
# 1383 already dropped the foreign keys these columns carried, so the drop needs a lock on
# posthog_taggeditem alone. Were a key still there, DROP COLUMN would drop it too and take
# ACCESS EXCLUSIVE on its parent, which is the lock order that deadlocked the first attempt.
DROP_COLUMNS = """
    ALTER TABLE posthog_taggeditem
        DROP COLUMN IF EXISTS dashboard_id,
        DROP COLUMN IF EXISTS insight_id,
        DROP COLUMN IF EXISTS event_definition_id,
        DROP COLUMN IF EXISTS property_definition_id,
        DROP COLUMN IF EXISTS action_id,
        DROP COLUMN IF EXISTS feature_flag_id,
        DROP COLUMN IF EXISTS experiment_saved_metric_id,
        DROP COLUMN IF EXISTS ticket_id,
        DROP COLUMN IF EXISTS account_id,
        DROP COLUMN IF EXISTS endpoint_id,
        DROP COLUMN IF EXISTS replay_scanner_id,
        DROP COLUMN IF EXISTS project_id,
        DROP COLUMN IF EXISTS experiment_id
"""

# The reverse brings the columns back empty, so the migration unapplies. It cannot bring the
# values back; the generic pointer is the only record of what each row tags. The types are the
# table's own: project is bigint, and the UUID-keyed models carry uuid.
ADD_COLUMNS = """
    ALTER TABLE posthog_taggeditem
        ADD COLUMN IF NOT EXISTS dashboard_id integer NULL,
        ADD COLUMN IF NOT EXISTS insight_id integer NULL,
        ADD COLUMN IF NOT EXISTS event_definition_id uuid NULL,
        ADD COLUMN IF NOT EXISTS property_definition_id uuid NULL,
        ADD COLUMN IF NOT EXISTS action_id integer NULL,
        ADD COLUMN IF NOT EXISTS feature_flag_id integer NULL,
        ADD COLUMN IF NOT EXISTS experiment_saved_metric_id integer NULL,
        ADD COLUMN IF NOT EXISTS ticket_id uuid NULL,
        ADD COLUMN IF NOT EXISTS account_id uuid NULL,
        ADD COLUMN IF NOT EXISTS endpoint_id uuid NULL,
        ADD COLUMN IF NOT EXISTS replay_scanner_id uuid NULL,
        ADD COLUMN IF NOT EXISTS project_id bigint NULL,
        ADD COLUMN IF NOT EXISTS experiment_id integer NULL
"""


def run_under_lock(sql):
    """Take the table lock under the deadlock budget, then run one statement holding it.

    Without this the ALTER TABLE waits out MIGRATE_LOCK_TIMEOUT, and every tag query that
    arrives meanwhile queues behind that waiting ACCESS EXCLUSIVE request.
    """

    def operation(apps, schema_editor):
        with transaction.atomic(using=schema_editor.connection.alias):
            lock_tables(schema_editor, ["posthog_taggeditem"])
            schema_editor.execute(sql)

    return operation


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1385_add_data_deletion_submission_id_constraint"),
    ]

    operations = [
        migrations.RunPython(run_under_lock(DROP_COLUMNS), run_under_lock(ADD_COLUMNS), elidable=False),
    ]

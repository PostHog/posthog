from django.db import migrations

# The table is append-only: `_set_value` soft-deletes the active row with an UPDATE and inserts
# the replacement, so every value change leaves a dead tuple behind. `is_deleted` sits in the
# predicate of the partial unique index, so the UPDATE cannot take the heap-only tuple path
# either — it also leaves a stale index entry. The scheduled warehouse sync rewrites every
# matched account on each run, so this churn is continuous rather than user-paced.
# The global autovacuum_vacuum_scale_factor of 0.1 makes autovacuum wait for 10% dead tuples,
# which is a large steady-state bloat load on a table whose reads go through that same index.
#
# SET (...) takes SHARE UPDATE EXCLUSIVE, which does not conflict with the value writes.
TABLE = "customer_analytics_custompropertyvalue"
SCALE_FACTOR = 0.02


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0056_feature_request_github"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Fail fast rather than queue: this waits behind an in-progress autovacuum
                # on the same table, and a retry is cheaper than holding the lock request.
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} SET (autovacuum_vacuum_scale_factor = {SCALE_FACTOR})",
            ],
            reverse_sql=[
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} RESET (autovacuum_vacuum_scale_factor)",
            ],
        ),
    ]

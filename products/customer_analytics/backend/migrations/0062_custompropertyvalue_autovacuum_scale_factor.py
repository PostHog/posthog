from django.db import migrations

# Every sync that changes a value soft-deletes the old row and inserts a new one. The soft delete
# changes the predicate of the partial unique index on active rows, so it cannot take the heap-only
# tuple path, and nothing hard-deletes rows. Each superseded value leaves a dead heap tuple and a
# dead entry in the partial index. The bulk reads of active values scan that index by team, so with
# the global scale factor of 0.1 they visit the dead entries and their heap pages until a pass runs.
# pganalyze flags this table for insufficient vacuuming. 0.02 matches the other tuned product
# tables, and the matching analyze factor keeps the planner statistics current.
#
# SET (...) takes SHARE UPDATE EXCLUSIVE, which does not conflict with the value writes.
TABLE = "customer_analytics_custompropertyvalue"
SCALE_FACTOR = 0.02


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0061_announcement_send_as"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Fail fast rather than queue: this waits behind an in-progress autovacuum
                # on the same table, and a retry is cheaper than holding the lock request.
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} SET ("
                f"autovacuum_vacuum_scale_factor = {SCALE_FACTOR}, "
                f"autovacuum_analyze_scale_factor = {SCALE_FACTOR})",
            ],
            reverse_sql=[
                "SET LOCAL lock_timeout = '5s'",
                f"ALTER TABLE {TABLE} RESET (autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)",
            ],
        ),
    ]

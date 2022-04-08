# This migration has been replaced by 0026_fix_materialized_window_and_session_ids
# The original migration led to potentially inconsistent names for materialized columns
# If the columns were created with this migration, they would be `$session_id` and `$window_id`,
# but if the columns were created with the normal column materialization job, they would be `mat_$session_id`
# and `mat_$window_id`. This led to potential inconsistencies between the tables state and the
# schema defined by `EVENTS_TABLE_SQL`

operations = []  # type: ignore

from posthog.models.raw_sessions.migrations import (
    update_raw_sessions_table,
    ADD_MAX_INSERTED_AT_COLUMN_SQL,
)

operations = update_raw_sessions_table(ADD_MAX_INSERTED_AT_COLUMN_SQL)

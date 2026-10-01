# Naming convention mirrors `property_values` — the AUX-resident, non-sharded
# table family:
#   * `hog_invocation_results_data` — local replicated table on AUX. Writes flow
#     in via the Kafka MV; replay reads happen against the distributed alias.
#   * `kafka_hog_invocation_results` — single Kafka engine table on AUX backed
#     by the warpstream-cyclotron named collection.
#   * `hog_invocation_results_mv` — MV on AUX, kafka → data table.
#   * `hog_invocation_results` — distributed read alias on AUX + DATA. This is
#     the name HogQL emits and the name the replay paginator queries.
HOG_INVOCATION_RESULTS_TABLE = "hog_invocation_results"
HOG_INVOCATION_RESULTS_DATA_TABLE = f"{HOG_INVOCATION_RESULTS_TABLE}_data"


# Direct insert used by tests / any bypass-Kafka producer. Writes go to the
# local data table (the distributed read alias isn't writable).
INSERT_HOG_INVOCATION_RESULT_SQL = f"""
INSERT INTO {HOG_INVOCATION_RESULTS_DATA_TABLE} (
    team_id,
    function_kind,
    function_id,
    invocation_id,
    parent_run_id,
    status,
    attempts,
    is_retry,
    scheduled_at,
    first_scheduled_at,
    started_at,
    finished_at,
    duration_ms,
    error_kind,
    error_message,
    event_uuid,
    distinct_id,
    person_id,
    invocation_globals,
    version,
    is_deleted,
    _timestamp,
    _offset,
    _partition
)
SELECT
    %(team_id)s,
    %(function_kind)s,
    %(function_id)s,
    %(invocation_id)s,
    %(parent_run_id)s,
    %(status)s,
    %(attempts)s,
    %(is_retry)s,
    %(scheduled_at)s,
    %(first_scheduled_at)s,
    %(started_at)s,
    %(finished_at)s,
    %(duration_ms)s,
    %(error_kind)s,
    %(error_message)s,
    %(event_uuid)s,
    %(distinct_id)s,
    %(person_id)s,
    %(invocation_globals)s,
    %(version)s,
    %(is_deleted)s,
    now(),
    0,
    0
"""

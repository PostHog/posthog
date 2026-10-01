# AUX-resident table family modelled on `hog_invocation_results`. One row per
# successfully sent email, keyed by (invocation_id, action_id) — a single
# workflow invocation can fan out to multiple email steps. Rendered HTML lives
# inline in the `html` column; columnar storage means listing queries don't read it.
MESSAGE_ASSETS_TABLE = "message_assets"
MESSAGE_ASSETS_DATA_TABLE = f"{MESSAGE_ASSETS_TABLE}_data"


# Writes go to the local data table — the distributed read alias isn't writable.
INSERT_MESSAGE_ASSET_SQL = f"""
INSERT INTO {MESSAGE_ASSETS_DATA_TABLE} (
    team_id,
    function_kind,
    function_id,
    parent_run_id,
    invocation_id,
    action_id,
    kind,
    distinct_id,
    person_id,
    recipient,
    subject,
    status,
    sent_at,
    version,
    is_deleted,
    html,
    _timestamp,
    _offset,
    _partition
)
SELECT
    %(team_id)s,
    %(function_kind)s,
    %(function_id)s,
    %(parent_run_id)s,
    %(invocation_id)s,
    %(action_id)s,
    %(kind)s,
    %(distinct_id)s,
    %(person_id)s,
    %(recipient)s,
    %(subject)s,
    %(status)s,
    %(sent_at)s,
    %(version)s,
    %(is_deleted)s,
    %(html)s,
    now(),
    0,
    0
"""

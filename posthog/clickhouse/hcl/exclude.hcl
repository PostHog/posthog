# Objects the convergence gate skips on a live node. Both gate steps read this
# one file: dump-live.sh passes it to `hclexp introspect -exclude` (a match is
# dropped before its DDL is parsed, so it never lands in the dump) and
# check-live.sh to `hclexp diff -exclude` (a match is dropped from both sides
# before diffing, so a golden-only match is not drift either). Patterns are
# filepath.Match globs against both the bare name ("events_main") and the
# db-qualified form ("posthog.events_main"); object_types drops a whole kind.
#
# Three classes live here:
#   1. Whole object kinds the goldens never model (object_types).
#   2. Transient objects (atomic-replace temporaries, migration/backfill scratch,
#      backups) — never part of the managed schema.
#   3. Cross-cluster proxies present on the node but intentionally NOT authored in
#      that role's golden — they belong to another role's managed set (e.g. the
#      events_* distributed proxies the OPS node carries so it can query the main
#      cluster). These are the same names check.sh lists in its validate SKIP.
#
# Grow this list from what the reconciliation pass surfaces — anything the live
# node has that the golden intentionally omits goes here, with a one-line reason.

exclude {
  # Secret Kafka broker/credential config; never modeled in the goldens.
  object_types = ["named_collection"]

  patterns = [
    # --- transient (ClickHouse atomic CREATE-OR-REPLACE / EXCHANGE) ---
    "_tmp_replace_*",

    # --- migration / ORM / backfill scratch ---
    "tmp_*",
    "*_tmp",
    "infi_clickhouse_orm_migrations*",

    # --- backups / staging / backfills ---
    "*_backup",
    "*_backup_*",
    "*_staging",
    "*_backfill",

    # --- cross-cluster proxies carried by the node but owned elsewhere ---
    # Distributed proxies into the main event cluster; owned by the data role.
    "events_main",
    "events_recent",

    # --- out-of-band managed: real on prod, not created by the local
    #     migrate_clickhouse path, so the gate ignores them on BOTH sides until
    #     a proper OPS migration reproduces them locally. Remove each entry once
    #     its migration lands. ---
    # custom_metrics* views are created on NodeRole.DATA (migration 0117), never
    # on the OPS node, yet prod OPS carries them (created out-of-band).
    "custom_metrics*",
    # Orphan: present on prod OPS but no migration or code creates it anywhere.
    "events_team_daily_stats",
  ]
}

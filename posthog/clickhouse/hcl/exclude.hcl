# Objects skipped when introspecting a live OPS/LOGS node for the convergence
# gate (verify-live.sh). A name matching any glob (filepath.Match syntax) is
# dropped before its DDL is parsed, so it neither lands in the introspected HCL
# nor is compared against the golden. Patterns match both the bare name
# ("events_main") and the db-qualified form ("posthog.events_main").
#
# Two classes live here:
#   1. Transient objects (atomic-replace temporaries, migration/backfill scratch,
#      backups) -- never part of the managed schema.
#   2. Cross-cluster proxies present on the node but intentionally NOT authored in
#      the OPS/LOGS golden -- they belong to another role's managed set (e.g. the
#      events_* distributed proxies the OPS node carries so it can query the main
#      cluster). These are the same names check.sh lists in its validate SKIP.
#
# Grow this list from what the reconciliation pass surfaces -- anything the live
# node has that the golden intentionally omits goes here, with a one-line reason.

exclude {
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
    # Distributed proxies into the main event cluster; not part of OPS/LOGS.
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

    # AUX webhook delivery-status family (migration 0287). Created by the
    # migrate path on AUX but not yet authored in the aux HCL layer, so the
    # live gate would otherwise flag it as drift. Reconcile into
    # roles/aux/shared (regenerate golden/ + sql/ via hclexp) and remove these.
    "warehouse_webhook_delivery_status",
    "warehouse_webhook_delivery_status_data",
    "warehouse_webhook_delivery_status_mv",
    "kafka_warehouse_webhook_delivery_status",
  ]
}

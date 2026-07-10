# Objects skipped when introspecting the single-node dev ClickHouse (env local-single).
# Same purpose as exclude.hcl, but only its *transient* class applies here.
#
# exclude.hcl drops two further classes that are wrong for this node:
#
#   1. Cross-cluster proxies owned by another role (events_main, events_recent). On a
#      one-node stack every cluster resolves to this node, so events_recent is a real
#      Distributed object here — and `events_batch_export_recent` reads from it, so
#      dropping it makes the schema fail validation.
#   2. Out-of-band-managed objects (custom_metrics*, events_team_daily_stats). The
#      custom_metrics_* suite IS created here: migration 0117 targets NodeRole.DATA,
#      and DEBUG routes every migration to NodeRole.ALL.
#
# Its `*_staging` / `*_backfill` globs are also too broad for this node — they match
# real objects (web_pre_aggregated_*_staging tables, *_batch_export_backfill views) —
# so this file spells the transient patterns out rather than reusing them wholesale.

exclude {
  patterns = [
    # --- transient (ClickHouse atomic CREATE-OR-REPLACE / EXCHANGE) ---
    "_tmp_replace_*",

    # --- migration / ORM scratch ---
    "tmp_*",
    "*_tmp",
    # infi.clickhouse_orm's applied-migration bookkeeping, not schema.
    "infi_clickhouse_orm_migrations",
    "infi_clickhouse_orm_migrations_distributed",

    # --- backups ---
    "*_backup",
    "*_backup_*",
  ]
}

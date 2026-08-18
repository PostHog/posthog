# Objects the convergence gate skips on the single-node dev ClickHouse (env local-single).
# Same two consumers as exclude.hcl — `hclexp introspect -exclude` in dump-live.sh and
# `hclexp diff -exclude` in check-live.sh — but its cross-cluster proxy class is wrong
# here: on a one-node stack every cluster resolves to this node, so events_main and
# events_recent are real Distributed objects, and `events_batch_export_recent` reads from
# events_recent, so dropping it makes the schema fail validation.
#
# exclude.hcl's `*_staging` / `*_backfill` globs are also too broad for this node — they
# match real objects (web_pre_aggregated_*_staging tables, *_batch_export_backfill views)
# — so this file spells the transient patterns out rather than reusing them wholesale.

exclude {
  # Secret Kafka broker/credential config; never modeled in the goldens.
  object_types = ["named_collection"]

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

    # --- out-of-band managed, same call as the multinode gate ---
    # Created out-of-band on cloud; what this node ends up with is an accident of DEBUG
    # routing every migration to one node, not declared intent.
    "custom_metrics*",
    # Orphan: no migration or code creates it; roles/coshared/custom_metrics models it
    # for the ops nodes, which do carry it.
    "events_team_daily_stats",
  ]
}

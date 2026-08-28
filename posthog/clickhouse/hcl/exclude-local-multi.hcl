# Per-env override of exclude.hcl for the local-multi convergence dump (dump-live.sh
# uses exclude-<env>.hcl when present, else exclude.hcl — it REPLACES, not merges, so
# this file must carry everything exclude.hcl does plus the local-multi-only entries).
#
# The only addition over exclude.hcl is the metrics-overlay ingest block: migration
# 0305 creates those objects on the LOGS node, but they are not modeled in the
# local-multi golden. On cloud they live in the roles/logs/shared + cloud layers and
# ARE checked (dev/prod keep using exclude.hcl); metrics1 itself diverges per env
# (value/count codecs on local + prod, none on dev), so a single all-env HCL
# declaration cannot serve both. Until that is reconciled, skip them here so the
# gate does not read migration-created objects as drift on local-multi.

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

    # --- metrics-overlay ingest: created by migration 0305 on LOGS, modeled in
    #     roles/logs/shared + cloud for dev/prod but not in the local golden.
    #     metrics1 diverges per env (codecs), so it is not yet in an all-env layer. ---
    "metrics1",
    "metrics",
    "metric_attributes",
    "metrics1_to_metric_attributes",
    "metrics1_to_resource_attributes",
    "metrics_kafka_metrics",
    "kafka_metrics_avro",
    "kafka_metrics_avro_mv",
    "kafka_metrics_avro_to_metric_samples",
    "kafka_metrics_avro_to_metric_series",
    "kafka_metrics_avro_kafka_metrics_mv",
  ]
}

"""Deployment topology for the OPS declarative-HCL → migration generator.

`node_roles` for a ClickHouse object is a deliberate engineering choice, NOT
something mechanically derivable from the dumps: the dump `hostClusterRole`
vocabulary (`ingestion`, `batch_exports`, `sessionsv3`, …) does not match the
`NodeRole` enum, and migrations deliberately target a curated subset rather than
every role that physically hosts an object.

So this map is the explicit source of truth for *where* each OPS-managed object
lives. It was seeded by introspecting ../clickhouse-schema (which roles host each
object) and reconciled against the existing OPS migrations (0273/0274). Keep it
in sync when adding or moving OPS objects — the generator errors on any object it
finds in a diff but not here, forcing a conscious choice.

Per object: (node_roles, replicated, sharded)
  node_roles  — NodeRole names the migration must target.
  replicated  — ReplicatedMergeTree family. Drives is_alter_on_replicated_table
                (an ALTER runs on one host per shard, replication propagates).
  sharded     — lives on the multi-shard DATA cluster. Every OPS satellite is
                single-shard, so this is False for all current OPS objects.
"""

# Every cluster on the query_log_archive read/write/MV path. Mirrors ALL_ROLES in
# migration 0273. ENDPOINTS is included per migration history even though it is
# not a distinct hostClusterRole in the dumps; the dump also shows ingestion/
# batch_exports/sessionsv3, which the migrations intentionally do not target.
ALL_ROLES = ["DATA", "ENDPOINTS", "AUX", "AI_EVENTS", "SESSIONS", "OPS"]

TOPOLOGY: dict[str, tuple[list[str], bool, bool]] = {
    # --- OPS data tables (single-shard, replicated) ---
    "sharded_query_log_archive": (["OPS"], True, False),
    "sharded_tophog": (["OPS"], True, False),
    "events_team_daily_stats": (["OPS"], True, False),
    "metrics_exemplars": (["OPS"], True, False),
    "metrics_histograms": (["OPS"], True, False),
    "metrics_label_index": (["OPS"], True, False),
    "metrics_metadata": (["OPS"], True, False),
    "metrics_samples": (["OPS"], True, False),
    "metrics_series": (["OPS"], True, False),
    # --- OPS-only, non-replicated (buffer / MV / distributed proxy / view) ---
    "query_log_archive_buffer": (["OPS"], False, False),
    "metrics_label_index_from_series_mv": (["OPS"], False, False),
    "events_main": (["OPS"], False, False),
    "daily_aggregated_query_log_archive": (["OPS"], False, False),
    # --- OPS + DATA ---
    "events_recent": (["OPS", "DATA"], False, False),
    # --- Everywhere: query_log_archive read/write path + custom_metrics views ---
    "query_log_archive": (ALL_ROLES, False, False),
    "writable_query_log_archive": (ALL_ROLES, False, False),
    "ops_query_log_archive_mv": (ALL_ROLES, False, False),
    "custom_metrics": (ALL_ROLES, False, False),
    "custom_metrics_backups": (ALL_ROLES, False, False),
    "custom_metrics_dictionaries": (ALL_ROLES, False, False),
    "custom_metrics_part_counts": (ALL_ROLES, False, False),
    "custom_metrics_replication_queue": (ALL_ROLES, False, False),
    "custom_metrics_server_crash": (ALL_ROLES, False, False),
    "custom_metrics_table_sizes": (ALL_ROLES, False, False),
    "custom_metrics_test": (ALL_ROLES, False, False),
}

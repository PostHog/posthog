from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE

LOG_ENTRIES_TABLE = "log_entries"
LOG_ENTRIES_SHARDED_TABLE = "sharded_log_entries"


INSERT_LOG_ENTRY_SQL = """
INSERT INTO log_entries SELECT %(team_id)s, %(log_source)s, %(log_source_id)s, %(instance_id)s, %(timestamp)s, %(level)s, %(message)s, now(), 0
"""

TRUNCATE_LOG_ENTRIES_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {LOG_ENTRIES_SHARDED_TABLE} {ON_CLUSTER_CLAUSE()}"

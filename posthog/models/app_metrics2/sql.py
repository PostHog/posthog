APP_METRICS2_TABLE = "app_metrics2"
APP_METRICS2_SHARDED_TABLE = f"sharded_{APP_METRICS2_TABLE}"


TRUNCATE_APP_METRICS2_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {APP_METRICS2_SHARDED_TABLE}"

# WarpStream Kafka engine tables (coexist alongside MSK tables, same target)


INSERT_APP_METRICS2_SQL = """
INSERT INTO sharded_app_metrics2 (
    team_id,
    timestamp,
    app_source,
    app_source_id,
    instance_id,
    metric_kind,
    metric_name,
    count,
    _timestamp,
    _offset,
    _partition
)
SELECT
    %(team_id)s,
    %(timestamp)s,
    %(app_source)s,
    %(app_source_id)s,
    %(instance_id)s,
    %(metric_kind)s,
    %(metric_name)s,
    %(count)s,
    now(),
    0,
    0
"""

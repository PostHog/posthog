# WarpStream Kafka engine tables (coexist alongside MSK tables, same target)


# This table is responsible for writing to sharded_ingestion_warnings based on a sharding key.


INSERT_INGESTION_WARNING = f"""
INSERT INTO sharded_ingestion_warnings (team_id, source, type, details, timestamp, _timestamp, _offset, _partition)
SELECT %(team_id)s, %(source)s, %(type)s, %(details)s, %(timestamp)s, now(), 0, 0
"""

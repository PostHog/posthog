# Speeds up filtering by _timestamp columns
def index_by_kafka_timestamp(table: str):
    return f"INDEX kafka_timestamp_minmax_{table} _timestamp TYPE minmax GRANULARITY 3"

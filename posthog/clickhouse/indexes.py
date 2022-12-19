# Speeds up selecting max(_timestamp)
def projection_for_max_kafka_timestamp(table: str):
    return f"PROJECTION fast_max_kafka_timestamp_{table} (SELECT max(_timestamp))"


# Speeds up filtering by _timestamp columns
def index_by_kafka_timestamp(table: str):
    return f"INDEX kafka_timestamp_minmax_{table} _timestamp TYPE minmax GRANULARITY 3"

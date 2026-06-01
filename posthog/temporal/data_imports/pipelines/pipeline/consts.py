DEFAULT_CHUNK_SIZE = 20_000
DEFAULT_TABLE_SIZE_BYTES = 150 * 1024 * 1024  # 150 MB
PARTITION_KEY = "_ph_partition_key"

# Delta Lake writer tuning: bounds writer + source memory during merges/writes.
MERGE_WRITE_BATCH_SIZE = 8_192
MERGE_MAX_ROW_GROUP_SIZE = 131_072
MERGE_SOURCE_CHUNK_SIZE = 10_000

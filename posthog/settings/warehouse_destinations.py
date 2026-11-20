from posthog.settings.utils import get_from_env

WAREHOUSE_DESTINATIONS_TRANSFORMER_MAX_WORKERS: int = get_from_env(
    "WAREHOUSE_DESTINATIONS_TRANSFORMER_MAX_WORKERS", 2, type_cast=int
)
WAREHOUSE_DESTINATIONS_PARQUET_MAX_BUFFERED_ARROW_BYTES: int = get_from_env(
    "WAREHOUSE_DESTINATIONS_PARQUET_MAX_BUFFERED_ARROW_BYTES",
    1024 * 1024 * 32,  # 32MB
    type_cast=int,
)
WAREHOUSE_DESTINATIONS_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES: int = get_from_env(
    "WAREHOUSE_DESTINATIONS_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES",
    1024 * 1024 * 50,  # 50MB
    type_cast=int,
)
# How long a REPLACE commit waits for the lock on the final table. Readers queue behind a waiting
# swap, so a short wait that fails and retries blocks them less than a long one.
WAREHOUSE_DESTINATIONS_POSTGRES_SWAP_LOCK_TIMEOUT_SECONDS: float = get_from_env(
    "WAREHOUSE_DESTINATIONS_POSTGRES_SWAP_LOCK_TIMEOUT_SECONDS", 60.0, type_cast=float
)

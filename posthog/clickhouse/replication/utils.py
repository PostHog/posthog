from posthog.models.async_migration import is_async_migration_complete
from posthog.settings import TEST

_is_replicated = False


def clickhouse_is_replicated() -> bool:
    # This is cached in a way where subsequent lookups don't result in queries if the migration is complete!
    global _is_replicated

    if _is_replicated:
        return True

    _is_replicated = is_async_migration_complete("0004_replicated_schema")
    return _is_replicated or TEST

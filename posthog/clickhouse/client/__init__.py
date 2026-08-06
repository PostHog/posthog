from typing import TYPE_CHECKING

from posthog.clickhouse.client.execute import query_with_columns, sync_execute

if TYPE_CHECKING:
    from posthog.clickhouse.client.execute_async import execute_process_query

__all__ = [
    "sync_execute",
    "query_with_columns",
    "execute_process_query",
]


# execute_async imports the schema/celery layers, and this package loads at django.setup()
# (async_migrations, kafka client). PEP 562 keeps the lazy name working for consumers.
def __getattr__(name: str) -> object:
    if name == "execute_process_query":
        from posthog.clickhouse.client.execute_async import execute_process_query  # noqa: PLC0415

        return execute_process_query
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

from posthog.hogql.direct_sql.adapter import DirectSQLAdapter

_ADAPTERS: dict[str, DirectSQLAdapter] = {}


def register_adapter(adapter: DirectSQLAdapter) -> None:
    _ADAPTERS[adapter.engine] = adapter


def get_adapter(engine: str | None) -> DirectSQLAdapter | None:
    if engine is None:
        return None
    return _ADAPTERS.get(engine)


def registered_engines() -> frozenset[str]:
    return frozenset(_ADAPTERS.keys())

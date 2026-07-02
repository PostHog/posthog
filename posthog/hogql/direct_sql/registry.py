from collections.abc import Callable

from posthog.hogql.direct_sql.adapter import DirectSQLAdapter

_ADAPTERS: dict[str, DirectSQLAdapter] = {}
_LAZY_FACTORIES: dict[str, Callable[[], DirectSQLAdapter]] = {}


def register_adapter(adapter: DirectSQLAdapter) -> None:
    _ADAPTERS[adapter.engine] = adapter


def register_lazy_adapter(engine: str, factory: Callable[[], DirectSQLAdapter]) -> None:
    """Register an adapter whose module is imported only on first use.

    Keeps a heavy dependency chain off the import path of everything that touches the
    registry — notably ``posthog.hogql.query`` — until a query for that engine actually runs.
    """
    _LAZY_FACTORIES[engine] = factory


def get_adapter(engine: str | None) -> DirectSQLAdapter | None:
    if engine is None:
        return None
    adapter = _ADAPTERS.get(engine)
    if adapter is not None:
        return adapter
    factory = _LAZY_FACTORIES.get(engine)
    if factory is None:
        return None
    adapter = factory()
    _ADAPTERS[engine] = adapter
    return adapter


def registered_engines() -> frozenset[str]:
    return frozenset(_ADAPTERS.keys()) | frozenset(_LAZY_FACTORIES.keys())

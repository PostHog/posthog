from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import DIRECT_ENGINE_BY_SOURCE_TYPE


def direct_capable_source_types() -> frozenset[str]:
    """Source types that map to a direct-SQL engine (the static capability surface)."""
    return frozenset(DIRECT_ENGINE_BY_SOURCE_TYPE.keys())


def is_direct_capable(source: ExternalDataSource) -> bool:
    """Whether this source can be queried live via a direct connection.

    Pure-direct sources are always capable. Synced (warehouse) sources are capable only when
    the per-source toggle is on. Either way the source type must map to a known engine.
    """
    if source.direct_engine is None:
        return False
    if source.access_method == ExternalDataSource.AccessMethod.DIRECT:
        return True
    return source.direct_query_enabled

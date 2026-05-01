"""Source-type adapters for CDC.

Each database engine needs its own adapter that knows how to:
- Create a stream reader (WAL / binlog / change stream)
- Open a management connection (for slot/publication lifecycle)
- Validate prerequisites (wal_level, permissions, PKs)
- Clean up resources (drop slot, drop publication)
- Check replication lag

Currently only Postgres is implemented. When adding MySQL or another engine,
create an adapter in ``sources/<engine>/cdc/adapter.py`` and register it below.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

if TYPE_CHECKING:
    from posthog.temporal.data_imports.cdc.types import CDCStreamReader

    from products.data_warehouse.backend.models import ExternalDataSource


ManagementMode = Literal["posthog", "self_managed"]


@dataclasses.dataclass(frozen=True)
class CDCConfig:
    """Base class for engine-specific CDC configs returned by ``parse_cdc_config``.

    Holds fields that apply to any change-stream engine (slot/publication-style
    identifiers, lag thresholds, management policy). Engine adapters return their
    own subclasses (e.g. ``PostgresCDCConfig``) and add engine-specific fields.
    """

    enabled: bool
    slot_name: str
    publication_name: str
    management_mode: ManagementMode
    lag_warning_threshold_mb: int
    lag_critical_threshold_mb: int
    auto_drop_slot: bool


CDCConfigT_co = TypeVar("CDCConfigT_co", bound=CDCConfig, covariant=True)


class CDCSourceAdapter(Protocol[CDCConfigT_co]):
    """Interface that each CDC-capable database engine must implement.

    Generic over the engine's concrete CDC config type so that ``parse_cdc_config``
    is typed precisely without forcing callers to do ``isinstance`` checks.
    """

    def create_reader(self, source: ExternalDataSource) -> CDCStreamReader: ...

    @contextmanager
    def management_connection(self, source: ExternalDataSource, connect_timeout: int = 15) -> Iterator[Any]: ...

    def validate_prerequisites(
        self,
        source: ExternalDataSource,
        management_mode: Literal["posthog", "self_managed"],
        tables: list[str],
        schema: str,
        slot_name: str | None,
        publication_name: str | None,
    ) -> list[str]: ...

    def drop_resources(self, conn: Any, slot_name: str, pub_name: str) -> None: ...

    def get_lag_bytes(self, conn: Any, slot_name: str) -> int | None: ...

    def parse_cdc_config(self, source: ExternalDataSource) -> CDCConfigT_co: ...


def get_cdc_adapter(source: ExternalDataSource) -> CDCSourceAdapter[CDCConfig]:
    """Return the CDC adapter for the given source's type.

    Raises ValueError if the source type doesn't support CDC.
    """
    from posthog.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter

    from products.data_warehouse.backend.types import ExternalDataSourceType

    adapters: dict[ExternalDataSourceType, CDCSourceAdapter[CDCConfig]] = {
        ExternalDataSourceType.POSTGRES: PostgresCDCAdapter(),
    }

    try:
        source_type = ExternalDataSourceType(source.source_type)
    except ValueError as e:
        raise ValueError(f"CDC is not supported for source type: {source.source_type}") from e

    adapter = adapters.get(source_type)
    if adapter is None:
        raise ValueError(f"CDC is not supported for source type: {source.source_type}")
    return adapter

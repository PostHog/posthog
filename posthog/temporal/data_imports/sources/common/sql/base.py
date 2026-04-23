"""`SQLSource` abstract base class for SQL-based data-import sources.

Every current SQL source (`PostgresSource`, `MySQLSource`, `MSSQLSource`,
`SnowflakeSource`, `BigQuerySource`, `RedshiftSource`, `ClickHouseSource`)
re-implements the same two methods on top of `SimpleSource`:

- `get_schemas` — open a tunnel, query `information_schema`, detect
  incremental fields, detect primary keys, assemble a list of `SourceSchema`.
- `source_for_pipeline` — open a tunnel, delegate to the driver's
  `<name>_source()` factory, return a `SourceResponse`.

This base class owns the orchestration and delegates driver-specific work
to two hooks (`_discover`, `_run_pipeline_source`). The discovery hook is
**atomic** — subclasses open their SSH tunnel / connection once and return
everything needed to build `SourceSchema` rows. This preserves today's
single-tunnel-per-listing behavior in `MySQLSource.get_schemas` and
`PostgresSource.get_schemas`.

**No behavior change today.** This class is additive — existing sources
that still inherit from `SimpleSource` directly continue to work unchanged.
The first subscriber is `MySQLSource`; other sources will migrate in
follow-up PRs (see `plans/for-all-the-sql-rosy-quiche.md`).
"""

from __future__ import annotations

import dataclasses
from abc import abstractmethod
from typing import Generic

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import ConfigType, SimpleSource
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
    build_incremental_fields,
)


@dataclasses.dataclass
class DiscoveryResult:
    """Everything `SQLSource.get_schemas` needs to build `SourceSchema` rows.

    Subclasses populate this in a single `_discover` call — typically inside
    a single SSH tunnel + connection — so `get_schemas` doesn't fan out into
    multiple network round-trips.
    """

    columns_by_table: dict[str, list[tuple[str, str, bool]]]
    primary_keys_by_table: dict[str, list[str] | None] = dataclasses.field(default_factory=dict)
    row_counts_by_table: dict[str, int | None] = dataclasses.field(default_factory=dict)
    foreign_keys_by_table: dict[str, list[tuple[str, str, str]]] = dataclasses.field(default_factory=dict)
    source_catalog_by_table: dict[str, str | None] = dataclasses.field(default_factory=dict)
    source_schema_by_table: dict[str, str | None] = dataclasses.field(default_factory=dict)
    source_table_name_by_table: dict[str, str | None] = dataclasses.field(default_factory=dict)
    supports_cdc_by_table: dict[str, bool] = dataclasses.field(default_factory=dict)


class SQLSource(SimpleSource[ConfigType], Generic[ConfigType]):
    """Base class for SQL-based data-import sources.

    Subclasses implement two hooks:

    - `_discover(config, names, with_counts)` — atomic schema discovery.
    - `_run_pipeline_source(config, inputs)` — build the pipeline's
      `SourceResponse`.

    …plus one zero-arg method (`_filter_incremental_fields`) that returns
    the driver's incremental-field filter.
    """

    source_display_name: str = "this database"
    """User-facing name for error messages. Override in subclasses."""

    # ------------------------------------------------------------------
    # Hooks every concrete subclass must implement
    # ------------------------------------------------------------------

    @abstractmethod
    def _discover(
        self,
        config: ConfigType,
        names: list[str] | None,
        with_counts: bool,
    ) -> DiscoveryResult:
        """Run the driver's `information_schema` queries in one shot.

        Subclasses should open their SSH tunnel (if any) once and query
        everything (columns, primary keys, row counts, foreign keys) before
        closing. `with_counts=False` — the default — lets subclasses skip
        potentially expensive row-count queries on the main listing path.
        """

    @abstractmethod
    def _filter_incremental_fields(self) -> IncrementalFieldFilter:
        """Return the driver's incremental-field filter.

        Called once per `get_schemas` invocation. Keeping this as a hook
        (rather than a classmethod) lets subclasses parameterize the filter
        on config if they ever need to.
        """

    @abstractmethod
    def _run_pipeline_source(
        self,
        config: ConfigType,
        inputs: SourceInputs,
    ) -> SourceResponse:
        """Build and return the `SourceResponse` for a live pipeline run.

        Exists as a separate method so `source_for_pipeline` can be a
        thin template. Subclasses typically delegate to their existing
        `<name>_source()` factory here.
        """

    # ------------------------------------------------------------------
    # Hook with sensible default — override only if needed
    # ------------------------------------------------------------------

    def _default_primary_key_from_columns(self, columns: list[tuple[str, str, bool]]) -> list[str] | None:
        """Fallback: if no PK was detected, use `id` when present.

        This matches what every SQL source does today just before building a
        `SourceSchema`. Extracted here so subclasses don't have to repeat it.
        """
        if any(col[0] == "id" for col in columns):
            return ["id"]
        return None

    # ------------------------------------------------------------------
    # Template methods (the reason this class exists)
    # ------------------------------------------------------------------

    def get_schemas(
        self,
        config: ConfigType,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
    ) -> list[SourceSchema]:
        result = self._discover(config, names, with_counts)
        if not result.columns_by_table:
            return []

        incremental_filter = self._filter_incremental_fields()

        schemas: list[SourceSchema] = []
        for table_name, columns in result.columns_by_table.items():
            incremental_triples = incremental_filter(columns)
            detected_pks = result.primary_keys_by_table.get(table_name)
            if not detected_pks:
                detected_pks = self._default_primary_key_from_columns(columns)

            schemas.append(
                SourceSchema(
                    name=table_name,
                    supports_incremental=len(incremental_triples) > 0,
                    supports_append=len(incremental_triples) > 0,
                    supports_cdc=result.supports_cdc_by_table.get(table_name, False),
                    incremental_fields=build_incremental_fields(incremental_triples),
                    columns=columns,
                    row_count=result.row_counts_by_table.get(table_name),
                    foreign_keys=result.foreign_keys_by_table.get(table_name, []),
                    source_catalog=result.source_catalog_by_table.get(table_name),
                    source_schema=result.source_schema_by_table.get(table_name),
                    source_table_name=result.source_table_name_by_table.get(table_name),
                    detected_primary_keys=detected_pks,
                )
            )
        return schemas

    def source_for_pipeline(self, config: ConfigType, inputs: SourceInputs) -> SourceResponse:
        return self._run_pipeline_source(config, inputs)

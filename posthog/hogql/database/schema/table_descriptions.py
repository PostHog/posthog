"""Unified table/column description resolution shared across schema surfaces.

Descriptions live in three places, resolved here in priority order per table/column:

  1. the static ``FieldOrTable.description`` set on native table definitions;
  2. ``WarehouseColumnAnnotation`` for physical data warehouse tables (keyed by table UUID);
  3. ``DataWarehouseSavedQueryColumnAnnotation`` for saved-query views (keyed by saved-query UUID).

A materialized view is a special case: when queried in materialized mode, HogQL swaps the view for
its single backing (output) warehouse table, so the table object carries the backing table's UUID
rather than the saved-query UUID. We keep a ``backing table UUID -> saved-query UUID`` map so a
materialized view still resolves its own view annotations instead of the (empty) backing-table ones.

``system.information_schema`` and the ``read_data`` agent tool both resolve descriptions through
this one class, so the two surfaces can never drift and neither has to re-implement the annotation
lookups. Load once per team (a few bulk queries) and reuse the instance across every table.
"""

from typing import Optional

import structlog

from posthog.hogql.database.models import FieldOrTable, SavedQuery, Table

logger = structlog.get_logger(__name__)


class TableDescriptions:
    def __init__(
        self,
        warehouse_descriptions: dict[tuple[str, str], str],
        view_descriptions: dict[tuple[str, str], str],
        view_by_backing_table: dict[str, str],
    ) -> None:
        # Descriptions keyed by ``(uuid, column_name)`` where ``column_name=""`` is the table/view-level
        # row. `view_by_backing_table` maps a materialized view's backing table UUID to its saved-query UUID.
        self._warehouse = warehouse_descriptions
        self._view = view_descriptions
        self._view_by_backing_table = view_by_backing_table

    @classmethod
    def load(cls, team_id: Optional[int]) -> "TableDescriptions":
        """Fetch every annotation for the team. Fail-soft: descriptions must never break a query or
        an agent tool, so a fetch error degrades to no descriptions (logged) rather than raising."""
        warehouse: dict[tuple[str, str], str] = {}
        view: dict[tuple[str, str], str] = {}
        view_by_backing_table: dict[str, str] = {}
        if team_id is None:
            return cls(warehouse, view, view_by_backing_table)

        # Inline imports: keep the products dependency off the hogql import path (products import
        # hogql, so a module-level import would cycle) and off every code path that never resolves
        # descriptions.
        from posthog.models.scoping import team_scope  # noqa: PLC0415

        from products.data_modeling.backend.facade.models import (  # noqa: PLC0415
            DataWarehouseSavedQuery,
            DataWarehouseSavedQueryColumnAnnotation,
        )
        from products.warehouse_sources.backend.facade.models import WarehouseColumnAnnotation  # noqa: PLC0415

        try:
            with team_scope(team_id):
                for table_id, column_name, description in WarehouseColumnAnnotation.objects.values_list(
                    "table_id", "column_name", "description"
                ):
                    warehouse[(str(table_id), column_name)] = description
                for sq_id, column_name, description in DataWarehouseSavedQueryColumnAnnotation.objects.values_list(
                    "saved_query_id", "column_name", "description"
                ):
                    view[(str(sq_id), column_name)] = description
                # `DataWarehouseSavedQuery` is not fail-closed team-scoped, so filter team_id explicitly.
                # A materialized view points at its backing output table via `table_id`.
                for backing_table_id, sq_id in (
                    DataWarehouseSavedQuery.objects.exclude(deleted=True)
                    .filter(team_id=team_id, table__isnull=False)
                    .values_list("table_id", "id")
                ):
                    view_by_backing_table[str(backing_table_id)] = str(sq_id)
        except Exception:
            logger.exception("table_descriptions: failed to load annotations", team_id=team_id)
            return cls({}, {}, {})

        return cls(warehouse, view, view_by_backing_table)

    def for_table(self, table: Table) -> Optional[str]:
        """Table-level description, dispatching on the table object: the static
        ``FieldOrTable.description`` (native tables) wins; a SavedQuery is a view (keyed by its
        saved-query id); anything carrying ``table_id`` is a warehouse table (or a materialized
        view's backing table, which resolves back to the view's annotations)."""
        if table.description:
            return table.description
        if isinstance(table, SavedQuery):
            return self._view.get((str(table.id), ""))
        table_id = getattr(table, "table_id", None)
        if table_id:
            return self._warehouse_or_view(str(table_id), "")
        return None

    def for_column(self, table: Table, column_name: str, field: Optional[FieldOrTable]) -> Optional[str]:
        if field is not None and field.description:
            return field.description
        if isinstance(table, SavedQuery):
            return self._view.get((str(table.id), column_name))
        table_id = getattr(table, "table_id", None)
        if table_id:
            return self._warehouse_or_view(str(table_id), column_name)
        return None

    def _warehouse_or_view(self, table_id: str, column_name: str) -> Optional[str]:
        # A materialized view's backing table carries view annotations, not warehouse ones.
        sq_id = self._view_by_backing_table.get(table_id)
        if sq_id is not None:
            return self._view.get((sq_id, column_name))
        return self._warehouse.get((table_id, column_name))

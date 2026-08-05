from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from django.db import models

import structlog

from posthog.models.resource_transfer.types import ResourceMap, ResourcePayload, ResourceTransferEdge
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)


class DataWarehouseSavedQueryVisitor(
    ResourceTransferVisitor,
    kind="DataWarehouseSavedQuery",
    friendly_name="Data warehouse view",
    excluded_fields=[
        # Materialization artifacts point at project-specific rows, so the copy must land fresh
        # and unmaterialized rather than inheriting the source's materialized table.
        "table",
        "managed_viewset",
        "folder",
        "deleted_name",
        # Test-view auto-expiry and the AI-description cache are recomputed per project.
        "is_test",
        "expires_at",
        "semantic_enrichment_hash",
        # Run bookkeeping — reset on the copy (see adjust_duplicate_payload).
        "status",
        "last_run_at",
        "latest_error",
        # S3 tables referenced by the source query are source-connection specific.
        "external_tables",
    ],
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

        return DataWarehouseSavedQuery

    @classmethod
    def get_dynamic_edges(cls, resource: Any) -> list[ResourceTransferEdge]:
        """Pull in the upstream views this query reads from.

        A saved query references its parents by name inside raw SQL (e.g. ``FROM revenue``),
        not by an ID in a typed column, so we resolve the query's parent names and add an edge
        for every parent that is itself a saved query in the same team. Parents that are physical
        warehouse tables / PostHog tables are not copied here — they need their own source setup
        in the destination project and are surfaced as non-portable references instead.
        """
        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

        parent_names = cls._resolve_parent_saved_query_names(resource)
        if not parent_names:
            return []

        parents = DataWarehouseSavedQuery.objects.filter(
            team_id=resource.team_id,
            name__in=parent_names,
            deleted=False,
        )

        edges: list[ResourceTransferEdge] = []
        for parent in parents:
            edges.append(
                ResourceTransferEdge(
                    name=f"saved_query_parent:{parent.name}",
                    target_model=DataWarehouseSavedQuery,
                    target_primary_key=parent.pk,
                    rewrite_relation=cls._make_parent_name_rewriter(parent.pk, parent.name),
                )
            )
        return edges

    @classmethod
    def adjust_duplicate_payload(
        cls,
        payload: ResourcePayload,
        vertex: Any,
        new_team: Team,
    ) -> ResourcePayload:
        """Land the copy as a fresh, unmaterialized view.

        The destination project has none of the source's materialized state, and the underlying
        data likely differs, so we clear the run status and let the destination decide whether and
        when to materialize.
        """
        result = {**payload}
        result["is_materialized"] = False
        result["sync_frequency_interval"] = None
        result["status"] = None
        result["last_run_at"] = None
        result["latest_error"] = None
        # Column schema is re-inferred when the view first runs in the destination project.
        result["columns"] = {}
        result["column_order"] = None
        return result

    @classmethod
    def deduplicate_name(cls, name: str, team: Team) -> str | None:
        """View names are SQL identifiers, so the default ``"<name> (Copy)"`` would be invalid.

        Use an identifier-safe ``<name>_copy`` / ``<name>_copy_2`` … suffix instead. When the name
        is free in the destination we keep it unchanged so sibling queries that reference it by name
        still resolve.
        """
        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

        taken: set[str] = set(
            DataWarehouseSavedQuery.objects.filter(team=team, name__startswith=name).values_list("name", flat=True)
        )
        if name not in taken:
            return name

        candidate = f"{name}_copy"
        if candidate not in taken:
            return candidate

        counter = 2
        while f"{name}_copy_{counter}" in taken:
            counter += 1
        return f"{name}_copy_{counter}"

    # -- helpers ---------------------------------------------------------------

    @classmethod
    def _resolve_parent_saved_query_names(cls, resource: Any) -> set[str]:
        query = resource.query or {}
        sql = query.get("query") if isinstance(query, dict) else None
        if not sql:
            return set()

        from products.data_modeling.backend.facade.modeling import get_parents_from_model_query

        try:
            return get_parents_from_model_query(resource.team, resource.name, sql)
        except Exception:
            # Lineage resolution is best-effort: if the query can't be parsed/resolved we copy the
            # view on its own rather than failing the whole transfer.
            logger.warning(
                "resource_transfer.saved_query.parent_resolution_failed",
                saved_query_id=str(resource.pk),
                exc_info=True,
            )
            return set()

    @classmethod
    def _make_parent_name_rewriter(cls, parent_pk: Any, old_name: str):
        """Rewrite references to a parent view when it was renamed on copy.

        In the common cross-project case the destination has no view of the same name, so the parent
        keeps its name and this is a no-op. When a collision forces a ``_copy`` rename, we point this
        query's SQL at the parent's new name so the lineage still resolves.
        """

        def _rewrite(payload: ResourcePayload, resource_map: ResourceMap) -> ResourcePayload:
            vertex = resource_map.get(("DataWarehouseSavedQuery", parent_pk))
            if vertex is None or vertex.duplicated_resource is None:
                return payload

            new_name = getattr(vertex.duplicated_resource, "name", None)
            if not new_name or new_name == old_name:
                return payload

            query = payload.get("query")
            if not isinstance(query, dict) or not query.get("query"):
                return payload

            # Replace whole-identifier occurrences only, so we don't touch substrings or column names.
            pattern = re.compile(rf"(?<![\w.]){re.escape(old_name)}(?![\w.])")
            result = {**payload}
            result["query"] = {**query, "query": pattern.sub(new_name, query["query"])}
            return result

        return _rewrite

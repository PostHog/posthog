from __future__ import annotations

from collections import Counter
from dataclasses import field
from typing import TYPE_CHECKING, Literal, TypedDict

import structlog

from posthog.schema import DatabaseSchemaQueryResponse

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import _schema_field_input, serialize_fields
from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.database.lazy_join_tags import GROUP_N
from posthog.hogql.database.models import (
    FieldOrTable,
    FieldTraverser,
    LazyJoin,
    SavedQuery,
    StringJSONDatabaseField,
    Table,
)
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.database.schema.event_sessions import EventsSessionSubTable
from posthog.hogql.database.schema.events import EventsGroupSubTable, EventsPersonSubTable, EventsTable
from posthog.hogql.database.schema.persons import PersonsTable
from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1
from posthog.hogql.database.schema.sessions_v2 import SessionsTableV2
from posthog.hogql.database.schema.sessions_v3 import SessionsTableV3
from posthog.hogql.errors import QueryError, ResolutionError

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

    from posthog.models import Team, User

logger = structlog.get_logger(__name__)

MAX_RELATION_DEFINITIONS = 4096
MAX_RELATION_FIELDS = 120_000
MAX_RESOLUTION_ATTEMPTS = 240_000
MAX_RESOLUTION_DEPTH = 16


@frozen
class CatalogTraversalResult:
    field_annotations: dict[str, dict[str, dict[str, str]]] = field(repr=False)
    relations: dict[str, CatalogRelationDefinition] = field(repr=False)


class CatalogRelationDefinition(TypedDict, total=False):
    fields: dict[str, dict[str, str]]
    table: str
    propertyNamespaces: dict[str, str]


@frozen
class _ResolvedTarget:
    target: FieldOrTable = field(repr=False)
    property_namespace: str | None
    parents: tuple[Table, ...] = field(repr=False)


@frozen
class _CanonicalTable:
    canonical_name: str = field(repr=False)
    expected_fields: set[str] = field(repr=False)
    table_type: Literal["posthog", "external"]


class _TraversalCatalogBuilder:
    def __init__(
        self,
        team: Team,
        user: User,
        schema: DatabaseSchemaQueryResponse,
        database: Database,
        property_namespaces: set[str],
    ) -> None:
        self.schema = schema
        self.database = database
        self.context = HogQLContext(team_id=team.pk, team=team, user=user, database=database)
        self.property_namespaces = property_namespaces
        self.annotations: dict[str, dict[str, dict[str, str]]] = {}
        self.relations: dict[str, CatalogRelationDefinition] = {}
        self.relation_keys: dict[tuple[object, ...], str] = {}
        self.omissions: Counter[str] = Counter()
        self.resolution_attempts = 0
        self.owned_fields = 0
        self.canonical_by_object = self._canonical_tables()
        self.canonical_name_cache: dict[int, str | None] = {}

    def build(self) -> CatalogTraversalResult:
        for canonical_name, schema_table in self.schema.tables.items():
            table = self._resolve_canonical(canonical_name)
            if table is None:
                continue
            table_annotations = self.annotations.setdefault(canonical_name, {})
            namespace = self._canonical_property_namespace(table)
            if (
                namespace is not None
                and "properties" in schema_table.fields
                and isinstance(table.fields.get("properties"), StringJSONDatabaseField)
            ):
                table_annotations["properties"] = {"propertyNamespace": namespace}
            for field_name in schema_table.fields:
                if "propertyNamespace" in table_annotations.get(field_name, {}):
                    continue
                field_value = table.fields.get(field_name)
                if field_value is None or not isinstance(field_value, (LazyJoin, FieldTraverser, Table)):
                    continue
                relation = self._relation_for_field(table, field_value, (), depth=0)
                if relation is not None:
                    table_annotations.setdefault(field_name, {})["relation"] = relation
            if not table_annotations:
                self.annotations.pop(canonical_name, None)

        if self.omissions:
            logger.warning("hogql_catalog_traversal_edges_omitted", reasons=dict(sorted(self.omissions.items())))
        return CatalogTraversalResult(field_annotations=self.annotations, relations=self.relations)

    def _canonical_tables(self) -> dict[int, _CanonicalTable]:
        candidates: dict[int, list[_CanonicalTable]] = {}
        visible_names = set(self.database.tables.resolve_visible_table_names())
        for canonical_name, schema_table in self.schema.tables.items():
            if canonical_name not in visible_names:
                continue
            table = self._resolve_canonical(canonical_name)
            if table is None:
                continue
            table_type: Literal["posthog", "external"] = (
                "posthog" if schema_table.type in ("posthog", "system") else "external"
            )
            candidates.setdefault(id(table), []).append(
                _CanonicalTable(
                    canonical_name=canonical_name,
                    expected_fields=set(schema_table.fields),
                    table_type=table_type,
                )
            )
        return {object_id: entries[0] for object_id, entries in candidates.items() if len(entries) == 1}

    def _resolve_canonical(self, name: str) -> Table | None:
        if not self._attempt_resolution():
            return None
        try:
            table = self.database.get_table(name)
        except (QueryError, ResolutionError):
            self.omissions["canonical_unresolvable"] += 1
            return None
        return table

    def _relation_for_field(
        self,
        owner: Table,
        field_value: FieldOrTable,
        parents: tuple[Table, ...],
        *,
        depth: int,
    ) -> str | None:
        if depth >= MAX_RESOLUTION_DEPTH or not self._attempt_resolution():
            self.omissions["resolution_limit"] += 1
            return None
        try:
            resolved = self._resolve_field_target(owner, field_value, parents, depth=depth)
        except Exception:
            self.omissions["target_unresolvable"] += 1
            return None
        target = resolved.target
        if not isinstance(target, Table) or target.hidden:
            return None

        overrides = self._property_overrides(resolved.property_namespace, target)
        canonical_name = self._canonical_name(target)
        if canonical_name is not None:
            canonical_fields = self.canonical_by_object[id(target)].expected_fields
            overrides = {name: namespace for name, namespace in overrides.items() if name in canonical_fields}
            return self._table_relation(target, canonical_name, overrides)
        if isinstance(target, (S3Table, SavedQuery, DirectSQLTable)):
            self.omissions["target_not_exported"] += 1
            return None
        return self._virtual_relation(target, resolved.parents, overrides, depth=depth + 1)

    def _canonical_name(self, target: Table) -> str | None:
        if id(target) in self.canonical_name_cache:
            return self.canonical_name_cache[id(target)]
        canonical = self.canonical_by_object.get(id(target))
        if canonical is None:
            return None
        try:
            serialized = serialize_fields(
                _schema_field_input(target),
                self.context,
                [canonical.canonical_name],
                table_type=canonical.table_type,
            )
        except Exception:
            self.omissions["canonical_unserializable"] += 1
            return None
        result = canonical.canonical_name if {field.name for field in serialized} == canonical.expected_fields else None
        self.canonical_name_cache[id(target)] = result
        return result

    def _resolve_field_target(
        self, owner: Table, field_value: FieldOrTable, parents: tuple[Table, ...], *, depth: int
    ) -> _ResolvedTarget:
        if isinstance(field_value, LazyJoin):
            return _ResolvedTarget(
                target=field_value.resolve_table(self.context),
                property_namespace=self._lazy_join_property_namespace(field_value),
                parents=(*parents, owner),
            )
        if isinstance(field_value, FieldTraverser):
            return self._resolve_chain(owner, field_value.chain, parents, depth=depth + 1)
        return _ResolvedTarget(target=field_value, property_namespace=None, parents=(*parents, owner))

    def _resolve_chain(
        self, owner: Table, chain: list[str | int], parents: tuple[Table, ...], *, depth: int
    ) -> _ResolvedTarget:
        if depth >= MAX_RESOLUTION_DEPTH:
            raise ResolutionError("catalog traversal chain is too deep")
        current: FieldOrTable = owner
        ancestors = list(parents)
        edge_namespace: str | None = None
        for component in chain:
            if not self._attempt_resolution():
                raise ResolutionError("catalog traversal resolution budget exceeded")
            if component == "..":
                if not ancestors:
                    raise ResolutionError("catalog traversal has no parent")
                current = ancestors.pop()
                continue
            if isinstance(current, LazyJoin):
                edge_namespace = self._lazy_join_property_namespace(current)
                current = current.resolve_table(self.context)
            if isinstance(current, FieldTraverser):
                resolved = self._resolve_chain(owner, current.chain, tuple(ancestors), depth=depth + 1)
                current = resolved.target
                edge_namespace = resolved.property_namespace
                ancestors = list(resolved.parents)
            if not isinstance(current, Table):
                raise ResolutionError("catalog traversal reached a scalar field")
            if current.hidden:
                raise ResolutionError("catalog traversal reached a hidden table")
            if isinstance(current, (S3Table, SavedQuery, DirectSQLTable)) and self._canonical_name(current) is None:
                raise ResolutionError("catalog traversal reached an unpublished table")
            next_value = current.fields[str(component)]
            if next_value.hidden:
                raise ResolutionError("catalog traversal reached a hidden field")
            was_traverser = False
            was_lazy_join = isinstance(next_value, LazyJoin)
            if isinstance(next_value, FieldTraverser):
                was_traverser = True
                resolved = self._resolve_chain(current, next_value.chain, tuple(ancestors), depth=depth + 1)
                next_value = resolved.target
                edge_namespace = resolved.property_namespace
                ancestors = list(resolved.parents)
            if isinstance(next_value, LazyJoin):
                edge_namespace = self._lazy_join_property_namespace(next_value)
                next_value = next_value.resolve_table(self.context)
            if isinstance(next_value, Table):
                if next_value.hidden:
                    raise ResolutionError("catalog traversal reached a hidden table")
                if not was_traverser:
                    ancestors.append(current)
                if not was_traverser and not was_lazy_join:
                    edge_namespace = None
            current = next_value
        if isinstance(current, LazyJoin):
            return _ResolvedTarget(
                target=current.resolve_table(self.context),
                property_namespace=self._lazy_join_property_namespace(current),
                parents=tuple(ancestors),
            )
        if isinstance(current, FieldTraverser):
            return self._resolve_chain(owner, current.chain, tuple(ancestors), depth=depth + 1)
        return _ResolvedTarget(target=current, property_namespace=edge_namespace, parents=tuple(ancestors))

    def _table_relation(self, target: Table, canonical_name: str, overrides: dict[str, str]) -> str | None:
        key = ("table", canonical_name, tuple(sorted(overrides.items())))
        if cached := self.relation_keys.get(key):
            return cached
        if not self._reserve_definition(len(overrides)):
            return None
        relation_name = self._new_relation_name()
        definition: CatalogRelationDefinition = {"table": canonical_name}
        if overrides:
            definition["propertyNamespaces"] = overrides
        self.relations[relation_name] = definition
        self.relation_keys[key] = relation_name
        return relation_name

    def _virtual_relation(
        self, target: Table, parents: tuple[Table, ...], overrides: dict[str, str], *, depth: int
    ) -> str | None:
        parent_context = id(parents[-1]) if parents and self._uses_parent(target) else 0
        key = ("virtual", id(target), parent_context, tuple(sorted(overrides.items())))
        if cached := self.relation_keys.get(key):
            return cached
        fields = self._serialize_table_fields(target)
        if fields is None or not self._reserve_definition(len(fields) + len(overrides)):
            return None
        relation_name = self._new_relation_name()
        definition: CatalogRelationDefinition = {"fields": fields}
        self.relations[relation_name] = definition
        self.relation_keys[key] = relation_name

        namespace = self._target_property_namespace(target)
        if namespace is not None and "properties" in fields:
            fields["properties"]["propertyNamespace"] = namespace
        for field_name, namespace_override in overrides.items():
            if field_name in fields:
                fields[field_name]["propertyNamespace"] = namespace_override
        for field_name, field_value in target.fields.items():
            if field_name not in fields or "propertyNamespace" in fields[field_name]:
                continue
            if not isinstance(field_value, (LazyJoin, FieldTraverser, Table)):
                continue
            nested_relation = self._relation_for_field(target, field_value, parents, depth=depth)
            if nested_relation is not None:
                fields[field_name]["relation"] = nested_relation
        return relation_name

    def _serialize_table_fields(self, target: Table) -> dict[str, dict[str, str]] | None:
        fields: dict[str, dict[str, str]] = {}
        for field_name, field_value in _schema_field_input(target).items():
            if not self._attempt_resolution():
                self.omissions["resolution_limit"] += 1
                return None
            try:
                serialized = serialize_fields({field_name: field_value}, self.context, ["relation"])
            except Exception:
                self.omissions["field_unserializable"] += 1
                continue
            if len(serialized) != 1:
                continue
            schema_field = serialized[0]
            fields[field_name] = {"name": schema_field.name or field_name, "type": schema_field.type}
        return fields

    def _uses_parent(self, target: Table) -> bool:
        return any(isinstance(value, FieldTraverser) and ".." in value.chain for value in target.fields.values())

    def _property_overrides(self, edge_namespace: str | None, target: Table) -> dict[str, str]:
        namespace = edge_namespace
        if namespace is None:
            namespace = self._target_property_namespace(target)
        properties_field = target.fields.get("properties")
        if namespace is None or not isinstance(properties_field, StringJSONDatabaseField) or properties_field.hidden:
            return {}
        return {"properties": namespace}

    def _lazy_join_property_namespace(self, field_value: LazyJoin) -> str | None:
        if field_value.resolver != GROUP_N:
            return None
        group_index = field_value.resolver_params.get("group_index")
        namespace = f"group:{group_index}" if isinstance(group_index, int) else None
        return namespace if namespace in self.property_namespaces else None

    def _target_property_namespace(self, target: Table) -> str | None:
        namespace: str | None = None
        if isinstance(target, EventsPersonSubTable):
            namespace = "person"
        elif isinstance(target, EventsSessionSubTable):
            namespace = "session"
        elif isinstance(target, EventsGroupSubTable):
            namespace = f"group:{target.group_index}"
        return namespace if namespace in self.property_namespaces else None

    def _canonical_property_namespace(self, target: Table) -> str | None:
        namespace: str | None = None
        if isinstance(target, EventsTable):
            namespace = "event"
        elif isinstance(target, PersonsTable):
            namespace = "person"
        elif isinstance(target, (SessionsTableV1, SessionsTableV2, SessionsTableV3)):
            namespace = "session"
        return namespace if namespace in self.property_namespaces else None

    def _reserve_definition(self, field_count: int) -> bool:
        if len(self.relations) >= MAX_RELATION_DEFINITIONS:
            self.omissions["definition_limit"] += 1
            return False
        if self.owned_fields + field_count > MAX_RELATION_FIELDS:
            self.omissions["field_limit"] += 1
            return False
        self.owned_fields += field_count
        return True

    def _new_relation_name(self) -> str:
        return f"relation_{len(self.relations)}"

    def _attempt_resolution(self) -> bool:
        self.resolution_attempts += 1
        return self.resolution_attempts <= MAX_RESOLUTION_ATTEMPTS


def build_catalog_traversals(
    team: Team,
    user: User,
    schema: DatabaseSchemaQueryResponse,
    database: Database,
    property_namespaces: set[str],
) -> CatalogTraversalResult:
    return _TraversalCatalogBuilder(team, user, schema, database, property_namespaces).build()

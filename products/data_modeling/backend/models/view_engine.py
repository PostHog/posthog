from typing import Any

from django.db import models
from django.db.models import Expression, JSONField, Value
from django.db.models.fields.json import KeyTransform

from posthog.dataclasses import frozen

RAW_TRINO_MATERIALIZE_REASON = "Views that run raw Trino SQL cannot be materialized yet."
RAW_TRINO_LINEAGE_REASON = "Views that run raw Trino SQL have no lineage, because only hosted Trino can parse them."
RAW_TRINO_CLICKHOUSE_REFERENCE_REASON = "HogQL queries cannot reference a view that runs raw Trino SQL."
CONNECTION_SAVE_REASON = (
    "Views can't be saved on a direct connection. Create the view in your own database, "
    "or save this query as an insight."
)
CONNECTION_MATERIALIZE_REASON = "Views that run on a direct connection cannot be materialized yet."
CONNECTION_LINEAGE_REASON = "Views that run on a direct connection have no lineage yet."
CONNECTION_CLICKHOUSE_REFERENCE_REASON = "HogQL queries cannot reference a view that runs on a direct connection."

_ANNOTATED_QUERY_KEYS = {
    "executionTarget": "engine_execution_target",
    "sendRawQuery": "engine_send_raw_query",
    "connectionId": "engine_connection_id",
}


class ViewEngineTarget(models.TextChoices):
    CLICKHOUSE = "clickhouse", "ClickHouse"
    MANAGED_TRINO = "managed_trino", "Hosted Trino"
    CONNECTION = "connection", "Direct connection"


class ViewEngineDialect(models.TextChoices):
    HOGQL = "hogql", "HogQL"
    RAW = "raw", "Raw SQL"


class ViewColumnSource(models.TextChoices):
    CLICKHOUSE_PROBE = "clickhouse_probe", "ClickHouse probe"
    CLIENT_TYPES = "client_types", "Column types sent by the client"


@frozen
class ViewCapability:
    available: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.available == (self.reason is not None):
            raise ValueError("A capability has a reason exactly when it is unavailable.")


_AVAILABLE = ViewCapability(available=True)


@frozen
class ViewEngine:
    """Which engine runs a saved query, and what the rest of the product can do with the view."""

    target: ViewEngineTarget
    dialect: ViewEngineDialect
    connection_id: str | None = None

    def __post_init__(self) -> None:
        if (self.target == ViewEngineTarget.CONNECTION) != (self.connection_id is not None):
            raise ValueError("A view has a connection id exactly when it runs on a direct connection.")

    @classmethod
    def from_query(cls, query: object) -> "ViewEngine":
        """The only reader of the engine keys on a saved query's JSON."""
        if not isinstance(query, dict):
            return cls(target=ViewEngineTarget.CLICKHOUSE, dialect=ViewEngineDialect.HOGQL)
        # The list annotation matches JSON `true` in SQL, so a truthy string must not count here either.
        send_raw = query.get("sendRawQuery") is True
        # Hosted Trino wins over a connection id, as in the HogQL query runner.
        if query.get("executionTarget") == ViewEngineTarget.MANAGED_TRINO:
            target, connection_id = ViewEngineTarget.MANAGED_TRINO, None
        elif isinstance(query.get("connectionId"), str) and query["connectionId"]:
            target, connection_id = ViewEngineTarget.CONNECTION, query["connectionId"]
        else:
            # ClickHouse runs HogQL only, so a stray `sendRawQuery` changes nothing there.
            return cls(target=ViewEngineTarget.CLICKHOUSE, dialect=ViewEngineDialect.HOGQL)
        return cls(
            target=target,
            dialect=ViewEngineDialect.RAW if send_raw else ViewEngineDialect.HOGQL,
            connection_id=connection_id,
        )

    @classmethod
    def queryset_annotations(cls, *, read_query_keys: bool) -> dict[str, Expression]:
        """Annotations that let `from_annotated` build the engine of a row whose `query` is deferred.

        Reading the keys still detoasts `query`. With `read_query_keys=False` every row reads as ClickHouse.
        """
        if read_query_keys:
            return {name: KeyTransform(key, "query") for key, name in _ANNOTATED_QUERY_KEYS.items()}
        return {name: Value(None, output_field=JSONField()) for name in _ANNOTATED_QUERY_KEYS.values()}

    @classmethod
    def from_annotated(cls, row: Any) -> "ViewEngine | None":
        """The engine from `queryset_annotations`, or None when the row carries no such annotations."""
        values = vars(row)
        if not all(name in values for name in _ANNOTATED_QUERY_KEYS.values()):
            return None
        return cls.from_query({key: values[name] for key, name in _ANNOTATED_QUERY_KEYS.items()})

    @property
    def is_raw_trino(self) -> bool:
        return self.target == ViewEngineTarget.MANAGED_TRINO and self.dialect == ViewEngineDialect.RAW

    @property
    def can_materialize(self) -> ViewCapability:
        return self._capability(raw_trino=RAW_TRINO_MATERIALIZE_REASON, connection=CONNECTION_MATERIALIZE_REASON)

    @property
    def has_lineage(self) -> ViewCapability:
        """Whether the view gets parsed for lineage and a node in the team's DAG."""
        return self._capability(raw_trino=RAW_TRINO_LINEAGE_REASON, connection=CONNECTION_LINEAGE_REASON)

    @property
    def referenceable_from_clickhouse(self) -> ViewCapability:
        """Whether a HogQL query on ClickHouse can read the view by name."""
        return self._capability(
            raw_trino=RAW_TRINO_CLICKHOUSE_REFERENCE_REASON, connection=CONNECTION_CLICKHOUSE_REFERENCE_REASON
        )

    @property
    def column_source(self) -> ViewColumnSource:
        """ClickHouse cannot run Trino SQL or a direct connection's SQL, so the client's result types are used instead."""
        if self.is_raw_trino or self.target == ViewEngineTarget.CONNECTION:
            return ViewColumnSource.CLIENT_TYPES
        return ViewColumnSource.CLICKHOUSE_PROBE

    def _capability(self, *, raw_trino: str, connection: str) -> ViewCapability:
        if self.is_raw_trino:
            return ViewCapability(available=False, reason=raw_trino)
        # Materialization, the DAG sync and the HogQL database read only `query["query"]` and run it on
        # ClickHouse or hosted Trino. They drop the connection id, so they would run the SQL against the wrong database.
        if self.target == ViewEngineTarget.CONNECTION:
            return ViewCapability(available=False, reason=connection)
        return _AVAILABLE

from typing import Any

import pytest

from posthog.hogql.errors import QueryError
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.transforms.trino.manifest import (
    TrinoCatalogManifest,
    TrinoManifestColumn,
    TrinoManifestTable,
    transpile_hogql_to_trino,
)

from posthog.schema_enums import DatabaseSerializedFieldType

pytestmark = pytest.mark.django_db


def _manifest(*tables: TrinoManifestTable) -> TrinoCatalogManifest:
    return TrinoCatalogManifest(tables=tables)


def _events() -> TrinoManifestTable:
    return TrinoManifestTable(
        logical_name="events",
        locator=("org_catalog", "posthog", "events_production"),
    )


def test_transpiles_core_table_with_values_without_django_queries(
    django_assert_num_queries: Any,
) -> None:
    with django_assert_num_queries(0):
        result = transpile_hogql_to_trino(
            "SELECT event FROM events WHERE event = {event}",
            manifest=_manifest(_events()),
            values={"event": "signup"},
            include_hogql=True,
        )

    assert result.sql == (
        'SELECT "org_catalog"."posthog"."events_production"."event" '
        'FROM "org_catalog"."posthog"."events_production" '
        'WHERE ("org_catalog"."posthog"."events_production"."event" = %(hogql_val_0)s) LIMIT 50000'
    )
    assert result.values == {"hogql_val_0": "signup"}
    assert result.hogql == "SELECT event FROM events WHERE equals(event, 'signup') LIMIT 50000"


def test_transpiles_manifest_table_without_django_queries(django_assert_num_queries: Any) -> None:
    orders = TrinoManifestTable(
        logical_name="stripe.orders",
        locator=("org_catalog", "imports", "stripe_orders"),
        columns=(
            TrinoManifestColumn(name="id", type=DatabaseSerializedFieldType.STRING, nullable=False),
            TrinoManifestColumn(name="total", type=DatabaseSerializedFieldType.DECIMAL),
        ),
    )

    with django_assert_num_queries(0):
        result = transpile_hogql_to_trino(
            "SELECT id, total FROM stripe.orders",
            manifest=_manifest(orders),
        )

    assert result.sql == (
        'SELECT "stripe__orders"."id", "stripe__orders"."total" '
        'FROM "org_catalog"."imports"."stripe_orders" AS "stripe__orders" LIMIT 50000'
    )
    assert result.values == {}


@pytest.mark.parametrize(
    ("query", "feature_code"),
    [
        ("SELECT matchesAction(1) FROM events", "TRINO_PURE_ACTION_UNSUPPORTED"),
        ("SELECT event FROM events WHERE person_id IN COHORT 1", "TRINO_PURE_COHORT_UNSUPPORTED"),
        ("SELECT event FROM events WHERE {filters}", "TRINO_PURE_PLACEHOLDER_UNSUPPORTED"),
    ],
)
def test_rejects_django_backed_semantics(query: str, feature_code: str) -> None:
    with pytest.raises(TrinoLoweringError) as error:
        transpile_hogql_to_trino(query, manifest=_manifest(_events()))

    assert error.value.feature_code == feature_code


def test_rejects_tables_absent_from_manifest() -> None:
    with pytest.raises(QueryError, match="Unknown table `saved_query`"):
        transpile_hogql_to_trino("SELECT * FROM saved_query", manifest=_manifest(_events()))

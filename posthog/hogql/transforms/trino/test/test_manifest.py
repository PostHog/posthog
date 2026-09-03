from typing import Any

import pytest
from unittest import mock

from posthog.schema import DateRange, HogQLFilters, HogQLQueryModifiers, HogQLVariable

from posthog.hogql.errors import QueryError
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.transforms.trino.manifest import (
    TrinoCatalogManifest,
    TrinoManifestColumn,
    TrinoManifestTable,
    build_trino_manifest_database,
    prepare_trino_catalog,
    transpile_hogql_to_trino,
)

from posthog.schema_enums import DatabaseSerializedFieldType, PersonsOnEventsMode

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


def test_prepared_catalog_reuses_metadata_and_isolates_query_state(django_assert_num_queries: Any) -> None:
    manifest = _manifest(_events())

    with (
        django_assert_num_queries(0),
        mock.patch(
            "posthog.hogql.transforms.trino.manifest.build_trino_manifest_database",
            wraps=build_trino_manifest_database,
        ) as build_database,
    ):
        catalog = prepare_trino_catalog(manifest)
        first = catalog.transpile("SELECT {value}", values={"value": "first"}, limit_top_select=False)
        second = catalog.transpile("SELECT {value}", values={"value": "second"})
        unnested = catalog.transpile("SELECT arrayJoin([1, 2])")

    build_database.assert_called_once_with(manifest)
    assert first.values == {"hogql_val_0": "first"}
    assert second.values == {"hogql_val_0": "second"}
    assert "LIMIT" not in first.sql
    assert second.sql.endswith("LIMIT 50000")
    assert "UNNEST" in unnested.sql

    first.values["hogql_val_0"] = "changed"
    assert second.values == {"hogql_val_0": "second"}


def test_manifest_relation_can_share_the_internal_unnest_function_name() -> None:
    relation = TrinoManifestTable(
        logical_name="__trino_unnest",
        locator=("org_catalog", "imports", "unnest_rows"),
        columns=(TrinoManifestColumn(name="value", type=DatabaseSerializedFieldType.STRING),),
    )

    result = transpile_hogql_to_trino(
        "SELECT value, arrayJoin([1, 2]) AS item FROM __trino_unnest",
        manifest=_manifest(relation),
    )

    assert 'FROM "org_catalog"."imports"."unnest_rows" AS "__trino_unnest"' in result.sql
    assert "CROSS JOIN UNNEST(transform(ARRAY[1, 2]" in result.sql


@pytest.mark.parametrize(
    ("query", "kwargs", "feature_code"),
    [
        ("SELECT matchesAction(1) FROM events", {}, "TRINO_PURE_ACTION_UNSUPPORTED"),
        ("SELECT event FROM events WHERE person_id IN COHORT 1", {}, "TRINO_PURE_COHORT_UNSUPPORTED"),
        ("SELECT event FROM events WHERE {filters}", {}, "TRINO_PURE_PLACEHOLDER_UNSUPPORTED"),
        (
            "SELECT event FROM events",
            {"filters": HogQLFilters(dateRange=DateRange(date_from="-7d"))},
            "TRINO_PURE_FILTERS_UNSUPPORTED",
        ),
        (
            "SELECT event FROM events",
            {"variables": {"value": HogQLVariable(code_name="value", variableId="1", value="signup")}},
            "TRINO_PURE_VARIABLES_UNSUPPORTED",
        ),
        (
            "SELECT event FROM events",
            {"modifiers": HogQLQueryModifiers(debug=True)},
            "TRINO_PURE_MODIFIER_UNSUPPORTED",
        ),
        (
            "SELECT event FROM events",
            {"modifiers": HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)},
            "TRINO_PERSONS_ON_EVENTS_MODE_UNSUPPORTED",
        ),
    ],
)
def test_rejects_django_backed_semantics(query: str, kwargs: dict[str, Any], feature_code: str) -> None:
    with pytest.raises(TrinoLoweringError) as error:
        transpile_hogql_to_trino(query, manifest=_manifest(_events()), **kwargs)

    assert error.value.feature_code == feature_code


def test_accepts_content_free_filters_and_null_modifiers() -> None:
    # Dashboards send an empty filters object, and a serialize/validate round trip carries every
    # unset modifier as an explicit null. Neither asks for Django semantics.
    result = transpile_hogql_to_trino(
        "SELECT event FROM events",
        manifest=_manifest(_events()),
        filters=HogQLFilters(),
        modifiers=HogQLQueryModifiers.model_validate({"debug": None, "materializationMode": None}),
    )

    assert 'FROM "org_catalog"."posthog"."events_production"' in result.sql


def test_rejects_tables_absent_from_manifest() -> None:
    with pytest.raises(QueryError, match="Unknown table `saved_query`"):
        transpile_hogql_to_trino("SELECT * FROM saved_query", manifest=_manifest(_events()))

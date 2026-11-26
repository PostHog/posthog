"""Tests for composing HogQL property filters into ClickHouse clauses."""

import typing

import pytest

from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import EVENTS_PROPERTIES_JSON_TYPE
from posthog.sync import database_sync_to_async

from products.batch_exports.backend.temporal.filters import InvalidFilterError, compose_filters_clause
from products.event_definitions.backend.models import PropertyDefinition

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


@pytest.mark.parametrize(
    "filters,expected_clause,expected_values",
    [
        # Events
        (
            [
                {"key": "$browser", "operator": "exact", "type": "event", "value": ["Firefox"]},
            ],
            """ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', ''), %(hogql_val_1)s), 0)""",
            {"hogql_val_0": "$browser", "hogql_val_1": "Firefox"},
        ),
        (
            [
                {"key": "$current_url", "operator": "icontains", "type": "event", "value": "https://posthog.com"},
            ],
            """ifNull(ilike(toString(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '')), %(hogql_val_1)s), 0)""",
            {"hogql_val_0": "$current_url", "hogql_val_1": "%https://posthog.com%"},
        ),
        (
            [
                {"key": "$browser", "operator": "exact", "type": "event", "value": ["Firefox"]},
                {"key": "test", "operator": "exact", "type": "event", "value": ["Test"]},
            ],
            """and(ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', ''), %(hogql_val_1)s), 0), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_2)s), ''), 'null'), '^"|"$', ''), %(hogql_val_3)s), 0))""",
            {"hogql_val_0": "$browser", "hogql_val_1": "Firefox", "hogql_val_2": "test", "hogql_val_3": "Test"},
        ),
        # Feature (subset of event)
        (
            [
                {"key": "$feature/some-feature", "type": "event", "operator": "exact", "value": ["true"]},
            ],
            """ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), \'\'), \'null\'), \'^"|"$\', \'\'), %(hogql_val_1)s), 0)""",
            {"hogql_val_0": "$feature/some-feature", "hogql_val_1": "true"},
        ),
        # Person
        (
            [
                {"key": "$initial_current_url", "type": "person", "operator": "exact", "value": ["http://localhost"]},
            ],
            """ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.person_properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', ''), %(hogql_val_1)s), 0)""",
            {"hogql_val_0": "$initial_current_url", "hogql_val_1": "http://localhost"},
        ),
        (
            [
                {"key": "$initial_current_url", "type": "person", "operator": "is_set", "value": None},
            ],
            """isNotNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.person_properties, %(hogql_val_0)s), \'\'), \'null\'), \'^"|"$\', \'\'))""",
            {"hogql_val_0": "$initial_current_url"},
        ),
        (
            [
                {"key": "$initial_current_url", "type": "person", "operator": "regex", "value": ["^http://.*$"]},
            ],
            """ifNull(match(toString(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.person_properties, %(hogql_val_0)s), \'\'), \'null\'), \'^"|"$\', \'\')), %(hogql_val_1)s), 0)""",
            {"hogql_val_0": "$initial_current_url", "hogql_val_1": "^http://.*$"},
        ),
        (
            [
                {"key": "$created_at", "type": "person", "operator": "between", "value": [0, 1]},
            ],
            """and(ifNull(greaterOrEquals(accurateCastOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.person_properties, %(hogql_val_0)s), \'\'), \'null\'), \'^"|"$\', \'\'), %(hogql_val_1)s), 0.0), 0), ifNull(lessOrEquals(accurateCastOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.person_properties, %(hogql_val_2)s), \'\'), \'null\'), \'^"|"$\', \'\'), %(hogql_val_3)s), 1.0), 0))""",
            {
                "hogql_val_0": "$created_at",
                "hogql_val_1": "Float64",
                "hogql_val_2": "$created_at",
                "hogql_val_3": "Float64",
            },
        ),
        # HogQL
        (
            [
                {"key": "toInt(properties.$browser_version) * 10 = 1", "type": "hogql", "value": None},
            ],
            """ifNull(equals(multiply(accurateCastOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), \'\'), \'null\'), \'^"|"$\', \'\'), %(hogql_val_1)s), 10), 1), 0)""",
            {"hogql_val_0": "$browser_version", "hogql_val_1": "Int64"},
        ),
    ],
    ids=[
        "events0",
        "events1",
        "events2",
        "feature0",
        "person0",
        "person1",
        "person2",
        "person3",
        "hogql0",
    ],
)
def test_compose_filters_clause(
    filters: list[dict[str, typing.Any]],
    expected_clause: str,
    expected_values: dict[str, str],
    ateam,
):
    result_clause, result_values = compose_filters_clause(filters, team_id=ateam.id)
    assert result_clause == expected_clause
    assert result_values == expected_values


def test_compose_filters_clause_prints_for_the_new_schema(ateam):
    """Filters printed for the new schema read typed paths and the `$feature_flags` map, not the properties text."""
    result_clause, result_values = compose_filters_clause(
        [
            {"key": "$browser", "type": "event", "operator": "exact", "value": ["Chrome"]},
            {"key": "$feature/checkout", "type": "event", "operator": "exact", "value": ["true"]},
        ],
        team_id=ateam.id,
        use_new_events_schema=True,
    )

    # `$browser` is read from its typed path. `$feature/checkout` is read from its own subcolumn of the `$feature_flags`
    # map, where a missing flag is '' and matches no filter value. 'true' also matches `$true`, the stored spelling of a
    # variant named "true", so the filter matches as it does on the legacy schema.
    expected_clause = """
        and(
            equals(events.properties.`$browser`, %(hogql_val_0)s),
            in(
                accurateCast(events.properties.`$feature_flags`.key_checkout, 'String'),
                tuple(%(hogql_val_1)s, %(hogql_val_2)s)
            )
        )
    """
    # The expected clause is indented for reading, so both sides are compared without whitespace. This is safe because
    # no literal in the clause contains whitespace: the filter values are query parameters.
    assert "".join(result_clause.split()) == "".join(expected_clause.split())
    assert result_values == {"hogql_val_0": "Chrome", "hogql_val_1": "true", "hogql_val_2": "$true"}


async def _evaluate_filters_clause(clause: str, values: dict, document: str, *, use_new_events_schema: bool) -> bool:
    """Run a filters clause against one event with the given properties and return whether the event matches."""
    # A clause for the new schema reads the typed JSON column, so the document is cast to the type the native table
    # stores. A clause for the legacy schema reads the String column as it is.
    properties = f"CAST(%(document)s, '{EVENTS_PROPERTIES_JSON_TYPE()}')" if use_new_events_schema else "%(document)s"

    result = await database_sync_to_async(sync_execute)(
        f"SELECT {clause} FROM (SELECT {properties} AS properties) AS events",
        {**values, "document": document},
    )

    return bool(result[0][0])


@pytest.mark.parametrize(
    "property_type,document,predicate,expected",
    [
        ("Numeric", '{"value":2.5}', "properties.value > 2", True),
        ("Numeric", '{"value":2.5}', "properties.value > 3", False),
        ("Numeric", '{"value":2.5}', "round(properties.value) = 2", True),
        ("Numeric", '{"value":2.5}', "round(properties.value) = 3", False),
        ("Boolean", '{"value":true}', "properties.value = true", True),
        ("Boolean", '{"value":false}', "properties.value = true", False),
    ],
)
@pytest.mark.parametrize("use_new_events_schema", [False, True])
async def test_filters_preserve_property_types(
    ateam, property_type, document, predicate, expected, use_new_events_schema
):
    """Filters on a property with a defined type compare it as that type, on both schemas."""
    await database_sync_to_async(PropertyDefinition.objects.create)(
        team=ateam, name="value", type=PropertyDefinition.Type.EVENT, property_type=property_type
    )
    clause, values = await database_sync_to_async(compose_filters_clause)(
        [{"key": predicate, "type": "hogql"}], team_id=ateam.id, use_new_events_schema=use_new_events_schema
    )

    matches = await _evaluate_filters_clause(clause, values, document, use_new_events_schema=use_new_events_schema)

    assert matches is expected


@pytest.mark.parametrize("use_new_events_schema", [False, True])
async def test_negated_flag_set_filter_skips_an_event_without_the_flag(ateam, use_new_events_schema):
    clause, values = await database_sync_to_async(compose_filters_clause)(
        [{"key": "NOT (properties.`$feature/checkout` IN ('test', 'control'))", "type": "hogql"}],
        team_id=ateam.id,
        use_new_events_schema=use_new_events_schema,
    )

    # The export query runs without HogQL's transform_null_in, so the missing flag's NULL keeps the event out.
    matches = await _evaluate_filters_clause(clause, values, '{"value":1}', use_new_events_schema=use_new_events_schema)

    assert matches is False


@pytest.mark.parametrize(
    "filters",
    (
        [
            {"key": "event in (select * from events)", "type": "hogql", "value": None},
        ],
        [
            {"key": "event =", "type": "hogql", "value": None},
        ],
    ),
    ids=[
        "hogql0",
        "hogql1",
    ],
)
def test_compose_filters_clause_raises(
    filters: list[dict[str, typing.Any]],
    ateam,
):
    with pytest.raises(InvalidFilterError):
        result_clause, result_values = compose_filters_clause(filters, team_id=ateam.id)

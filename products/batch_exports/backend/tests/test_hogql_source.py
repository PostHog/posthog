import pytest

from posthog.sync import database_sync_to_async

from products.batch_exports.backend.hogql_source import (
    UnsupportedHogQLQueryError,
    validate_hogql_query_for_batch_export,
)

pytestmark = pytest.mark.django_db


async def _validate(hogql_query: str, team) -> None:
    # Resolving the query reads from Postgres to build the team database, so run it off the event loop.
    await database_sync_to_async(validate_hogql_query_for_batch_export)(hogql_query, team)


@pytest.mark.parametrize(
    "hogql_query",
    [
        "SELECT event AS event, distinct_id AS distinct_id FROM events",
        "SELECT event AS event FROM events UNION ALL SELECT event AS event FROM events",
        "SELECT event AS event, timestamp AS timestamp FROM events "
        "WHERE timestamp >= {data_interval_start} AND timestamp < {data_interval_end}",
        # the placeholders may feed any expression, not only a plain comparison
        "SELECT event AS event FROM events "
        "WHERE timestamp >= {data_interval_start} - INTERVAL 2 DAY AND timestamp < {data_interval_end}",
        # each member of a UNION must resolve on its own, and placeholders may appear in any of them
        "SELECT event AS event, timestamp AS timestamp FROM events "
        "WHERE timestamp >= {data_interval_start} AND timestamp < {data_interval_end} "
        "UNION ALL SELECT event AS event, timestamp AS timestamp FROM events "
        "WHERE timestamp >= {data_interval_start} AND timestamp < {data_interval_end}",
        # placeholders inside a CTE are found and replaced too
        "WITH bounded AS (SELECT event AS event FROM events "
        "WHERE timestamp >= {data_interval_start} AND timestamp < {data_interval_end}) "
        "SELECT event AS event FROM bounded",
    ],
    ids=[
        "no-placeholders",
        "union-without-placeholders",
        "bounded-query",
        "placeholder-in-expression",
        "union-with-placeholders",
        "cte-with-placeholders",
    ],
)
async def test_accepts_valid_queries(ateam, hogql_query):
    await _validate(hogql_query, ateam)


@pytest.mark.parametrize(
    "hogql_query,expected_message",
    [
        ("SELECT does_not_exist FROM events", "Unable to resolve field: does_not_exist"),
        ("SELECT count() FROM events", "must be a field or have an alias"),
        ("SELECT event AS event FROM events WHERE {filters}", "Unsupported placeholder"),
        ("SELECT event AS event FROM events WHERE event = {concat('a', 'b')}", "Unsupported placeholder"),
        ("SELECT event AS event FROM events WHERE event = {unknown_placeholder}", "Unknown placeholder"),
        # the query must still resolve once the placeholders are substituted
        (
            "SELECT event AS event FROM events WHERE does_not_exist >= {data_interval_start}",
            "Unable to resolve field: does_not_exist",
        ),
    ],
    ids=[
        "unknown-field",
        "unaliased-expression",
        "filters-placeholder",
        "expression-placeholder",
        "unknown-placeholder",
        "unknown-field-in-placeholder-comparison",
    ],
)
async def test_rejects_unsupported_queries(ateam, hogql_query, expected_message):
    with pytest.raises(UnsupportedHogQLQueryError, match=expected_message):
        await _validate(hogql_query, ateam)

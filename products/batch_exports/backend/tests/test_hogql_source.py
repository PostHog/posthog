import pytest

from posthog.sync import database_sync_to_async

from products.batch_exports.backend.hogql_source import (
    UnsupportedHogQLQueryError,
    validate_hogql_query_for_batch_export,
)

pytestmark = pytest.mark.django_db


async def _validate(hogql_query: str, team, data_interval_field: str | None = None) -> None:
    # Resolving the query reads from Postgres to build the team database, so run it off the event loop.
    await database_sync_to_async(validate_hogql_query_for_batch_export)(hogql_query, team, data_interval_field)


@pytest.mark.parametrize(
    "hogql_query,data_interval_field",
    [
        ("SELECT event AS event, distinct_id AS distinct_id FROM events", None),
        ("SELECT event AS event FROM events UNION ALL SELECT event AS event FROM events", None),
        ("SELECT event AS event, timestamp AS timestamp FROM events", "timestamp"),
        ("SELECT event AS event, toStartOfHour(timestamp) AS hour FROM events GROUP BY event, hour", "hour"),
        (
            "SELECT event AS event, timestamp AS timestamp FROM events "
            "UNION ALL SELECT event AS event, timestamp AS timestamp FROM events",
            "timestamp",
        ),
    ],
    ids=["select", "union", "column-as-interval-field", "alias-as-interval-field", "union-with-interval-field"],
)
async def test_accepts_valid_queries(ateam, hogql_query, data_interval_field):
    await _validate(hogql_query, ateam, data_interval_field)


@pytest.mark.parametrize(
    "hogql_query,data_interval_field,expected_message",
    [
        ("SELECT does_not_exist FROM events", None, "Unable to resolve field: does_not_exist"),
        ("SELECT event FROM events WHERE {filters}", None, "Placeholders are not supported"),
        ("SELECT count() FROM events", None, "must be a field or have an alias"),
        ("SELECT event AS event FROM events", "not_a_field", "Unable to resolve field: not_a_field"),
        # The bounds apply to every member of a UNION, so the field must resolve in each of them.
        (
            "SELECT event AS event FROM events UNION ALL SELECT toString(id) AS event FROM persons",
            "timestamp",
            "Unable to resolve field: timestamp",
        ),
    ],
    ids=[
        "unknown-field",
        "placeholder",
        "unaliased-expression",
        "unknown-interval-field",
        "interval-field-missing-in-union-member",
    ],
)
async def test_rejects_unsupported_queries(ateam, hogql_query, data_interval_field, expected_message):
    with pytest.raises(UnsupportedHogQLQueryError, match=expected_message):
        await _validate(hogql_query, ateam, data_interval_field)

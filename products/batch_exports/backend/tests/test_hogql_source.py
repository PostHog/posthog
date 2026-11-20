import typing
from contextlib import nullcontext

import pytest
from unittest.mock import patch

from django.test import override_settings

from posthog.models.event.new_events_schema import EVENTS_TABLE_ROLLOUT_FLAG, EVENTS_TABLE_SELF_SERVE_FLAG
from posthog.models.instance_setting import override_instance_config
from posthog.sync import database_sync_to_async

from products.batch_exports.backend.hogql_source import (
    UnsupportedHogQLQueryError,
    apply_hogql_batch_export_modifier_defaults,
    create_hogql_context_for_batch_export,
    load_hogql_modifiers,
    validate_hogql_query_for_batch_export,
)

if typing.TYPE_CHECKING:
    from posthog.models import Team, User

pytestmark = pytest.mark.django_db


async def _validate(hogql_query: str, team: "Team", user: "User") -> None:
    # Resolving the query reads from Postgres to build the team database, so run it off the event loop.
    await database_sync_to_async(validate_hogql_query_for_batch_export)(hogql_query, team, user=user)


@pytest.mark.parametrize(
    "hogql_query",
    [
        "SELECT event AS event, distinct_id AS distinct_id FROM events",
        """
        SELECT event AS event
        FROM events
        UNION ALL
        SELECT event AS event
        FROM events
        """,
        """
        SELECT
            event AS event,
            timestamp AS timestamp
        FROM events
        WHERE
            timestamp >= {data_interval_start}
            AND timestamp < {data_interval_end}
        """,
        # the placeholders may feed any expression, not only a plain comparison
        """
        SELECT event AS event
        FROM events
        WHERE
            timestamp >= {data_interval_start} - INTERVAL 2 DAY
            AND timestamp < {data_interval_end}
        """,
        # each member of a UNION must resolve on its own, and placeholders may appear in any of them
        """
        SELECT
            event AS event,
            timestamp AS timestamp
        FROM events
        WHERE
            timestamp >= {data_interval_start}
            AND timestamp < {data_interval_end}
        UNION ALL
        SELECT
            event AS event,
            timestamp AS timestamp
        FROM events
        WHERE
            timestamp >= {data_interval_start}
            AND timestamp < {data_interval_end}
        """,
        # placeholders inside a CTE are found and replaced too
        """
        WITH bounded AS (
           SELECT event AS event FROM events
           WHERE
               timestamp >= {data_interval_start}
               AND timestamp < {data_interval_end}
           )
        SELECT event AS event FROM bounded
        """,
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
async def test_accepts_valid_queries(ateam, auser, hogql_query):
    await _validate(hogql_query, ateam, auser)


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
async def test_rejects_unsupported_queries(ateam, auser, hogql_query, expected_message):
    with pytest.raises(UnsupportedHogQLQueryError, match=expected_message):
        await _validate(hogql_query, ateam, auser)


@pytest.mark.parametrize(
    "team_modifiers,export_modifiers,expected_modifiers",
    [
        (None, None, {}),
        ({"convertToProjectTimezone": False}, None, {"convertToProjectTimezone": False}),
        (
            {"convertToProjectTimezone": False, "optimizeProjections": False},
            {"convertToProjectTimezone": True, "removedModifier": True},
            {"convertToProjectTimezone": True, "optimizeProjections": False},
        ),
    ],
    ids=["no-modifiers", "team-modifiers", "export-modifiers-override-team-modifiers"],
)
def test_create_hogql_context_for_batch_exports(
    team,
    team_modifiers: dict[str, typing.Any] | None,
    export_modifiers: dict[str, typing.Any] | None,
    expected_modifiers: dict[str, typing.Any],
) -> None:
    if team_modifiers is not None:
        team.modifiers = team_modifiers

    context = create_hogql_context_for_batch_export(team, modifiers=load_hogql_modifiers(export_modifiers))

    assert context.team == team

    for key, value in expected_modifiers.items():
        assert getattr(context.modifiers, key) == value, (
            f"Context modifier '{key}' should be '{value}', got '{getattr(context.modifiers, key)}'"
        )


def test_context_without_hogql_defaults_keeps_the_project_timezone(team) -> None:
    context = create_hogql_context_for_batch_export(team)

    assert context.modifiers.convertToProjectTimezone is True


@pytest.mark.parametrize(
    "instance_setting,flag_on,export_modifiers,expected",
    [
        ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA", None, None, False),
        ("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", None, None, False),
        (None, EVENTS_TABLE_ROLLOUT_FLAG, None, False),
        (None, EVENTS_TABLE_SELF_SERVE_FLAG, None, False),
        (None, None, {"useNewEventsSchema": True}, True),
    ],
    ids=["global-setting", "staff-list", "rollout-flag", "project-opt-in", "export-modifier"],
)
def test_only_the_export_modifier_moves_an_export_to_the_new_events_table(
    team,
    instance_setting: str | None,
    flag_on: str | None,
    export_modifiers: dict[str, typing.Any] | None,
    expected: bool,
) -> None:
    team.modifiers = {"useNewEventsSchema": True}
    setting_value = True if instance_setting == "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA" else str(team.pk)
    with (
        override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False),
        override_instance_config(instance_setting, setting_value) if instance_setting else nullcontext(),
        patch("posthog.models.event.new_events_schema.is_cloud", return_value=True),
        patch(
            "posthog.models.event.new_events_schema.posthoganalytics.feature_enabled",
            side_effect=lambda flag, *args, **kwargs: flag == flag_on,
        ),
    ):
        context = create_hogql_context_for_batch_export(
            team,
            modifiers=apply_hogql_batch_export_modifier_defaults(team, load_hogql_modifiers(export_modifiers)),
        )

        assert context.uses_new_events_schema() is expected


def test_load_hogql_modifiers_rejects_invalid_values() -> None:
    with pytest.raises(UnsupportedHogQLQueryError, match="Invalid HogQL modifiers"):
        load_hogql_modifiers({"personsOnEventsMode": "not_a_mode"})

from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import patch

from braintrust import EvalCase, Score
from pydantic import BaseModel

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.sync import database_sync_to_async

from products.data_warehouse.backend.max_tools import HogQLGeneratorArgs, HogQLGeneratorNode, HogQLGeneratorTool

from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.eval.scorers import SQLSemanticsCorrectness, SQLSyntaxCorrectness
from ee.hogai.utils.markdown import remove_markdown
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.warehouse import serialize_database_schema
from ee.models.assistant import Conversation


class EvalInput(BaseModel):
    instructions: str
    current_query: str | None = None
    apply_patch: Callable[[HogQLGeneratorTool], Any] | None = None


@pytest.fixture
def call_generate_hogql_query(demo_org_team_user):
    _, team, user = demo_org_team_user

    async def callable(inputs: EvalInput, *args, **kwargs) -> str:
        # Create a conversation for the thread_id
        conversation = await Conversation.objects.acreate(team=team, user=user)

        # Initial state for the graph
        tool = HogQLGeneratorTool(team=team, user=user, state=AssistantState(messages=[]))

        if inputs.apply_patch:
            inputs.apply_patch(tool)

        # Invoke the graph. The state will be updated through planner and then generator.
        result = await tool.ainvoke(
            HogQLGeneratorArgs(instructions=inputs.instructions).model_dump(),
            {
                "configurable": {
                    "thread_id": conversation.id,
                    "team": team,
                    "user": user,
                    "contextual_tools": {
                        tool.name: {
                            "current_query": inputs.current_query,
                        },
                    },
                }
            },
        )

        return remove_markdown(result)

    return callable


@pytest.fixture
async def database_schema(demo_org_team_user):
    team = demo_org_team_user[1]
    database = await database_sync_to_async(Database.create_for)(team=team)
    context = HogQLContext(team=team, enable_select_queries=True, database=database)
    return await serialize_database_schema(database, context)


async def sql_syntax_scorer(input: EvalInput, expected: str, output: str, **kwargs) -> Score:
    metadata: dict = kwargs["metadata"]
    metric = SQLSyntaxCorrectness()
    return await metric._run_eval_async(output=output, team=metadata["team"])


async def sql_semantics_scorer(input: EvalInput, expected: str, output: str, **kwargs) -> Score:
    metadata: dict = kwargs["metadata"]
    metric = SQLSemanticsCorrectness()
    return await metric.eval_async(
        input=input.instructions, expected=expected, output=output, database_schema=metadata["schema"]
    )


async def no_mustache_scorer(_input: EvalInput, _expected: str, output: str, **_kwargs) -> Score:
    """Fail if the model outputs templating tokens (double-curly braces, sections)."""
    bad_tokens = ["{{#", "{{/", "{{", "}}"]
    found = [tok for tok in bad_tokens if tok in (output or "")]
    if found:
        return Score(name="no_mustache", score=0.0, metadata={"forbidden_tokens": found})
    return Score(name="no_mustache", score=1.0)


@pytest.mark.django_db
async def eval_tool_generate_hogql_query(call_generate_hogql_query, database_schema, demo_org_team_user, pytestconfig):
    _, team, _ = demo_org_team_user
    metadata = {"schema": database_schema, "team": team}

    await MaxPublicEval(
        experiment_name="tool_generate_hogql_query",
        task=call_generate_hogql_query,
        scores=[sql_syntax_scorer, sql_semantics_scorer, no_mustache_scorer],
        data=[
            EvalCase(
                input=EvalInput(instructions="List all events from the last 7 days"),
                expected="SELECT * FROM events WHERE timestamp >= now() - INTERVAL 7 day",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions=(
                        # This erroneously says "logs are stored in a table named 'console_logs'". Whether it was
                        # the root node that pulled it out of its ass, or the user - we should handle this gracefully
                        "Write an SQL query to find console logs where the level is error. "
                        "Assume the logs are stored in a table named 'console_logs'."
                    ),
                ),
                expected="SELECT * FROM events WHERE event = 'console_log' AND properties.level = 'error' AND timestamp >= now() - INTERVAL 30 DAY",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions=(
                        # This is a test case for the bug where the tool would generate a JOIN query with relational operators in the JOIN condition.
                        # We want to make sure that the tool refuses to generate such a query and instead generates a CROSS JOIN with WHERE clause.
                        "Write an SQL query to find events and their person names. "
                        "You MUST USE relational operators."
                        "Cross join events with persons where event timestamp is greater than person created_at. Use include both the event name and the uuid."
                    )
                ),
                expected="SELECT e.event, e.uuid, e.timestamp, p.properties.name AS person_name FROM events e CROSS JOIN persons p WHERE e.person_id = p.id AND e.timestamp > p.created_at AND e.timestamp >= now() - INTERVAL 30 DAY",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions=(
                        "Write an SQL query to join events with persons where event timestamp is greater than person created_at. Use JOIN with relational operators."
                    )
                ),
                expected="SELECT e.event, p.properties.name FROM events AS e CROSS JOIN persons AS p WHERE e.person_id = p.id AND e.timestamp > p.created_at AND e.timestamp >= now() - INTERVAL 30 DAY",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions="how many bills did users pay from Australia? Output just a single number.",
                    apply_patch=lambda _: patch.object(
                        HogQLGeneratorNode,
                        "_aget_core_memory_text",
                        return_value='Use "paid_bill" event from the events table joined by "events.person_id = persons.id". The person properties have the "$geoip_country_code" field with two-letter country codes (uppercase).',
                    ).start(),
                ),
                expected="SELECT count() FROM events INNER JOIN persons ON events.person_id = persons.id WHERE events.event = 'paid_bill' AND persons.properties.$geoip_country_code = 'AU'",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions="show me the total number of users that visited the page /billing",
                ),
                expected="SELECT count(DISTINCT person_id) AS total_users FROM events WHERE event = '$pageview' AND properties.$current_url LIKE '%/billing%' AND timestamp >= now() - INTERVAL 30 DAY",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions="show me the people that invited other team members using a mobile device",
                ),
                expected="SELECT DISTINCT person.id, person.properties.email, person.properties.name FROM events WHERE event = 'invited_team_member' AND properties.$device_type = 'Mobile' AND timestamp >= now() - INTERVAL 30 DAY",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions="Count the browser versions currently used by all users, and finally there are three columns: browser, browser version, and number of users",
                ),
                expected="SELECT person.properties.$browser AS browser, person.properties.$browser_version AS browser_version, count(DISTINCT person.id) AS number_of_users FROM events WHERE timestamp >= now() - INTERVAL 30 DAY GROUP BY browser, browser_version ORDER BY number_of_users DESC",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions="Count the browser languages currently used by users that signed up, and finally there are three columns: browser, browser language, and number of users. Include the time period from the 1st of January 2025 to the 1st of February 2025",
                ),
                expected="SELECT properties.$browser AS browser, properties.$browser_language AS browser_language, count(DISTINCT person_id) AS number_of_users FROM events WHERE event = 'signed_up' AND timestamp >= '2025-01-01T00:00:00:000' AND timestamp <= '2025-02-01T23:59:59:999' GROUP BY browser, browser_language ORDER BY number_of_users DESC",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions="want to see a pattern of traffic volume across all weekdays (for example, a breakdown showing counts for each weekday)",
                ),
                expected="SELECT toDayOfWeek(timestamp) AS weekday, count() AS event_count FROM events WHERE timestamp >= now() - INTERVAL 30 DAY GROUP BY weekday ORDER BY weekday",
                metadata=metadata,
            ),
            EvalCase(
                # This is a test case where we test the retry mechanism
                # The table postgres.connection_logs is not available in the database, so the model should retry and find the correct table
                input=EvalInput(
                    instructions="Tweak the current one to satisfy this request: List all devices, grouping by lowercased description, and for each group, use the description from the most recent event as 'dispositivo'. Exclude devices where the description contains 'piero', 'test', 'local', or 'totem' (case-insensitive). Show columns: 'dispositivo' (description from the most recent event), 'status' ('online' if latest event is 'enter', else 'offline'), and 'last event ts' (timestamp). Order by status ('online' first), then by dispositivo ASC. The current query is: \nSELECT anyLast(la.description) AS dispositivo, if(anyLast(cl.event) = 'enter', 'online', 'offline') AS status, anyLast(cl.timestamp) AS 'last event ts' FROM (SELECT license_activation_id, event,timestamp FROM postgres.connection_logs WHERE license_activation_id IS NOT NULL ORDER BY timestamp ASC) AS cl JOIN postgres.license_activations AS la ON cl.license_activation_id = la.id WHERE  NOT (lower(la.description) LIKE '%piero%' OR lower(la.description) LIKE '%test%' OR lower(la.description) LIKE '%local%' OR lower(la.description) LIKE '%totem%') GROUP BY lower(la.description) ORDER BY status DESC, dispositivo ASC",
                ),
                expected="SELECT anyLast(properties.description) AS dispositivo, if(anyLast(event) = 'enter', 'online', 'offline') AS status, anyLast(timestamp) AS last event ts FROM events WHERE properties.description IS NOT NULL AND NOT ( lower(properties.description) LIKE '%piero%' OR lower(properties.description) LIKE '%test%' OR lower(properties.description) LIKE '%local%' OR lower(properties.description) LIKE '%totem%' ) AND timestamp >= now() - INTERVAL 30 DAY GROUP BY lower(properties.description) ORDER BY status DESC, dispositivo ASC",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(instructions="How many unique users visited our site last week?"),
                expected="SELECT count(DISTINCT person_id) FROM events WHERE event = '$pageview' AND timestamp >= now() - INTERVAL 7 DAY",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions="Show me the number of unique registered users who performed a purchase event in the last 30 days"
                ),
                expected="SELECT count(DISTINCT person_id) FROM events WHERE event = 'purchase' AND timestamp >= now() - INTERVAL 30 DAY",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    instructions="Get the daily count of unique users (including anonymous) who triggered any event, broken down by day for the past 2 weeks"
                ),
                expected="SELECT toStartOfDay(timestamp) AS day, count(DISTINCT person_id) AS unique_users FROM events WHERE timestamp >= now() - INTERVAL 14 DAY GROUP BY day ORDER BY day DESC",
                metadata=metadata,
            ),
            EvalCase(
                input=EvalInput(
                    current_query="""SELECT
    p.id AS person_id,
    p.properties.email AS email,
    p.properties.org AS organization
FROM persons p
WHERE p.properties.email NOT LIKE '%@test.com'
ORDER BY p.created_at DESC
LIMIT 1000""",
                    instructions="Update the query to use variables.org for filtering. If variables.org is null, do not filter by organization. If variables.org is set, filter so that p.properties.org = variables.org.",
                ),
                expected="SELECT p.id AS person_id, p.properties.email AS email, p.properties.org AS organization FROM persons p WHERE p.properties.email NOT LIKE '%@test.com' AND (coalesce(variables.org, '') = '' OR p.properties.org = variables.org) ORDER BY p.created_at DESC LIMIT 1000",
                metadata=metadata,
            ),
        ],
        pytestconfig=pytestconfig,
    )

# ruff: noqa: E402

import datetime
import os
from django.core.wsgi import get_wsgi_application

os.environ["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "1"
os.environ["TEST"] = "1"
application = get_wsgi_application()

from posthog.clickhouse.client.execute import sync_execute
from django.conf import settings
from infi.clickhouse_orm import Database
from braintrust import Eval
from autoevals import LLMClassifier
from django.test import override_settings
from ee.hogai.utils.types import AssistantState, AssistantMessage, AssistantNodeName
from ee.hogai.graph import AssistantGraph
from django.test.runner import DiscoverRunner as TestRunner
from posthog.conftest import create_clickhouse_tables
from posthog.demo.matrix.manager import MatrixManager
from posthog.demo.products.hedgebox.matrix import HedgeboxMatrix
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.schema import HumanMessage


def call_graph(team: Team, message: str) -> AssistantMessage:
    graph = (
        AssistantGraph(team)
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            {
                "insights": AssistantNodeName.END,
                "docs": AssistantNodeName.END,
                "root": AssistantNodeName.END,
                "end": AssistantNodeName.END,
            }
        )
        .compile()
    )
    raw_state = graph.invoke(AssistantState(messages=[HumanMessage(content=message)]))
    state = AssistantState.model_validate(raw_state)
    assert isinstance(state.messages[-1], AssistantMessage)
    return state.messages[-1]


no_apology = LLMClassifier(
    name="No apology",
    prompt_template="Does the response contain an apology? (Y/N)\n\n{{output}}",
    choice_scores={"Y": 0, "N": 1},
    use_cot=True,
)


def prep_root_data():
    # Let's ensure Postgres schema
    test_runner = TestRunner(interactive=False, keepdb=True)
    test_runner.setup_databases()
    test_runner.setup_test_environment()
    # Let's ensure ClickHouse schema and data
    should_generate_fresh_data = True
    database = Database(
        settings.CLICKHOUSE_DATABASE,
        db_url=settings.CLICKHOUSE_HTTP_URL,
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        cluster=settings.CLICKHOUSE_CLUSTER,
        verify_ssl_cert=settings.CLICKHOUSE_VERIFY,
        randomize_replica_paths=True,
    )
    if database.db_exists:
        try:
            max_event_timestamp_rows = sync_execute("SELECT max(timestamp) FROM events")[0]
        except Exception as e:
            if "Unknown table expression identifier 'events'" in str(e):
                max_event_timestamp_rows = None  # No events table
            else:
                raise
        if max_event_timestamp_rows and max_event_timestamp_rows[0].date() >= datetime.date.today():
            print(f"Using existing ClickHouse database ('{settings.CLICKHOUSE_DATABASE}')...")  # noqa: T201
            should_generate_fresh_data = False
        else:
            print(f"Dropping stale ClickHouse database ('{settings.CLICKHOUSE_DATABASE}')...")  # noqa: T201
            database.drop_database()
    if should_generate_fresh_data:
        print(f"Creating ClickHouse database ('{settings.CLICKHOUSE_DATABASE}')...")  # noqa: T201
        database.create_database()  # Create database if it doesn't exist
        create_clickhouse_tables()
        # Let's get demo data in
        organization, team, user = User.objects.bootstrap(
            "Hedgebox",
            "eval@posthog.com",
            "password1234",
            team_fields={
                "test_account_filters": [
                    {
                        "key": "email",
                        "value": "@posthog.com",
                        "operator": "not_icontains",
                        "type": "person",
                    }
                ],
                "has_completed_onboarding_for": {"product_analytics": True},
            },
        )
        matrix = HedgeboxMatrix(
            seed="b1ef3c66-5f43-488a-98be-6b46d92fbcef",  # this seed generates all events
            days_past=120,
            days_future=30,
            n_clusters=500,
            group_type_index_offset=0,
        )
        matrix_manager = MatrixManager(matrix, print_steps=True)
        with override_settings(TEST=False):
            # Simulation saving should occur in non-test mode, so that Kafka isn't mocked. Normally in tests we don't
            # want to ingest via Kafka, but simulation
            matrix_manager.run_on_team(team, user)

    # Let's return the eval dataset
    return [
        {
            "input": "David",
            "expected": "Hi David",
        }
    ]


Eval(
    "PostHog",
    data=prep_root_data,  # Replace with your eval dataset
    task=lambda input: "Sorry " + input,  # Replace with your LLM call
    scores=[no_apology],
)

import os
from collections.abc import Generator

import pytest
from django.test import override_settings
from langchain_core.runnables import RunnableConfig

from ee.models import Conversation
from posthog.conftest import create_clickhouse_tables
from posthog.demo.matrix.manager import MatrixManager
from posthog.models import Organization, Project, Team, User
from posthog.tasks.demo_create_data import HedgeboxMatrix
from posthog.test.base import BaseTest, run_clickhouse_statement_in_parallel


# Apply decorators to all tests in the package.
def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(
            pytest.mark.skipif(os.environ.get("DEEPEVAL") != "YES", reason="Only runs for the assistant evaluation")
        )
        item.add_marker(pytest.mark.flaky(max_runs=3, min_passes=1))


@pytest.fixture(scope="module")
def team(django_db_blocker) -> Generator[Team, None, None]:
    with django_db_blocker.unblock():
        organization = Organization.objects.create(name=BaseTest.CONFIG_ORGANIZATION_NAME)
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=organization)
        team = Team.objects.create(
            id=project.id,
            project=project,
            organization=organization,
            test_account_filters=[
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                }
            ],
            has_completed_onboarding_for={"product_analytics": True},
        )
        yield team
        organization.delete()


@pytest.fixture(scope="module")
def user(team, django_db_blocker) -> Generator[User, None, None]:
    with django_db_blocker.unblock():
        user = User.objects.create_and_join(team.organization, "eval@posthog.com", "password1234")
        yield user
        user.delete()


@pytest.mark.django_db(transaction=True)
@pytest.fixture
def runnable_config(team, user) -> Generator[RunnableConfig, None, None]:
    conversation = Conversation.objects.create(team=team, user=user)
    yield {
        "configurable": {
            "thread_id": conversation.id,
        }
    }
    conversation.delete()


@pytest.fixture(scope="module", autouse=True)
def setup_kafka_tables(django_db_setup):
    from posthog.clickhouse.client import sync_execute
    from posthog.clickhouse.schema import (
        CREATE_KAFKA_TABLE_QUERIES,
        build_query,
    )
    from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

    kafka_queries = list(map(build_query, CREATE_KAFKA_TABLE_QUERIES))
    run_clickhouse_statement_in_parallel(kafka_queries)

    # Re-create the tables depending on Kafka tables.
    create_clickhouse_tables(0)

    yield

    # Drop the tables, so some other tests don't fail.
    kafka_tables = sync_execute(
        f"""
        SELECT name
        FROM system.tables
        WHERE database = '{CLICKHOUSE_DATABASE}' AND name LIKE 'kafka_%'
        """,
    )
    kafka_truncate_queries = [f"DROP TABLE {table[0]} ON CLUSTER '{CLICKHOUSE_CLUSTER}'" for table in kafka_tables]
    run_clickhouse_statement_in_parallel(kafka_truncate_queries)


@pytest.fixture(scope="module", autouse=True)
def setup_test_data(setup_kafka_tables, team, user, django_db_blocker):
    with django_db_blocker.unblock():
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
            # want to ingest via Kafka, but simulation saving is specifically designed to use that route for speed
            matrix_manager.run_on_team(team, user)

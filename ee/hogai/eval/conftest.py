import functools
from collections.abc import Generator
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from langchain_core.runnables import RunnableConfig

from ee.models import Conversation
from ee.models.assistant import CoreMemory
from posthog.demo.matrix.manager import MatrixManager
from posthog.models import Organization, Project, Team, User
from posthog.tasks.demo_create_data import HedgeboxMatrix
from posthog.test.base import BaseTest


# Flaky is a handy tool, but it always runs setup fixtures for retries.
# This decorator will just retry without re-running setup.
def retry_test_only(max_retries=3):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    print(f"\nRetrying test (attempt {attempt + 1}/{max_retries})...")  # noqa
            if last_error:
                raise last_error

        return wrapper

    return decorator


# Apply decorators to all tests in the package.
def pytest_collection_modifyitems(items):
    current_dir = Path(__file__).parent
    for item in items:
        if Path(item.fspath).is_relative_to(current_dir):
            item.add_marker(
                pytest.mark.skipif(not settings.IN_EVAL_TESTING, reason="Only runs for the assistant evaluation")
            )
            # Apply our custom retry decorator to the test function
            item.obj = retry_test_only(max_retries=3)(item.obj)


@pytest.fixture(scope="package")
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


@pytest.fixture(scope="package")
def user(team, django_db_blocker) -> Generator[User, None, None]:
    with django_db_blocker.unblock():
        user = User.objects.create_and_join(team.organization, "eval@posthog.com", "password1234")
        yield user
        user.delete()


@pytest.fixture(scope="package")
def core_memory(team) -> Generator[CoreMemory, None, None]:
    initial_memory = """Hedgebox is a cloud storage service enabling users to store, share, and access files across devices.

    The company operates in the cloud storage and collaboration market for individuals and businesses.

    Their audience includes professionals and organizations seeking file management and collaboration solutions.

    Hedgebox’s freemium model provides free accounts with limited storage and paid subscription plans for additional features.

    Core features include file storage, synchronization, sharing, and collaboration tools for seamless file access and sharing.

    It integrates with third-party applications to enhance functionality and streamline workflows.

    Hedgebox sponsors the YouTube channel Marius Tech Tips."""

    core_memory = CoreMemory.objects.create(
        team=team,
        text=initial_memory,
        initial_text=initial_memory,
        scraping_status=CoreMemory.ScrapingStatus.COMPLETED,
    )
    yield core_memory
    core_memory.delete()


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


@pytest.fixture(scope="package", autouse=True)
def setup_test_data(django_db_setup, team, user, django_db_blocker):
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

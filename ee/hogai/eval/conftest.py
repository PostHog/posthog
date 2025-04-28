import datetime
import functools
from collections.abc import Generator

import pytest
from django.test import override_settings

from ee.models.assistant import CoreMemory
from posthog.clickhouse.client.execute import sync_execute
from posthog.demo.matrix.manager import MatrixManager
from posthog.models import Organization, Team, User
from posthog.tasks.demo_create_data import HedgeboxMatrix


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


@pytest.fixture(scope="package")
def org_team_user(django_db_blocker) -> Generator[tuple[Organization, Team, User], None, None]:
    with django_db_blocker.unblock():
        try:
            user = User.objects.get(email="eval@posthog.com")
        except User.DoesNotExist:
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
        else:
            organization = user.current_organization
            team = user.current_team
        yield organization, team, user


@pytest.fixture(scope="package")
def core_memory(org_team_user) -> Generator[CoreMemory, None, None]:
    initial_memory = """Hedgebox is a cloud storage service enabling users to store, share, and access files across devices.

    The company operates in the cloud storage and collaboration market for individuals and businesses.

    Their audience includes professionals and organizations seeking file management and collaboration solutions.

    Hedgebox’s freemium model provides free accounts with limited storage and paid subscription plans for additional features.

    Core features include file storage, synchronization, sharing, and collaboration tools for seamless file access and sharing.

    It integrates with third-party applications to enhance functionality and streamline workflows.

    Hedgebox sponsors the YouTube channel Marius Tech Tips."""

    core_memory = CoreMemory.objects.get_or_create(
        team=org_team_user[1],
        text=initial_memory,
        initial_text=initial_memory,
        scraping_status=CoreMemory.ScrapingStatus.COMPLETED,
    )
    yield core_memory


@pytest.fixture(scope="package", autouse=True)
def setup_test_data(django_db_setup, org_team_user, django_db_blocker):
    with django_db_blocker.unblock():
        max_event_timestamp_rows = sync_execute("SELECT max(timestamp) FROM events")[0]
        if max_event_timestamp_rows and max_event_timestamp_rows[0].date() >= datetime.date.today():
            print(f"Using existing demo data for evals...")  # noqa: T201
        else:
            print(f"Generating fresh demo data for evals...")  # noqa: T201
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
                matrix_manager.run_on_team(org_team_user[1], org_team_user[2])

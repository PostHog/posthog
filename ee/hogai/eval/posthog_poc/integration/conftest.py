from __future__ import annotations

import datetime
from collections.abc import Generator

import pytest

from django.test import override_settings

from posthog.demo.matrix.manager import MatrixManager
from posthog.models import Organization, Team, User
from posthog.tasks.demo_create_data import HedgeboxMatrix

from ee.models.assistant import CoreMemory

EVAL_USER_FULL_NAME = "Karen Smith"


@pytest.fixture(scope="session", autouse=True)
def demo_org_team_user(
    set_up_evals,  # noqa: F811
    django_db_blocker,
) -> Generator[tuple[Organization, Team, User], None, None]:
    with django_db_blocker.unblock():
        team: Team | None = Team.objects.order_by("-created_at").first()
        today = datetime.date.today()
        if not team or team.created_at.date() < today:
            print("Generating fresh demo data for PostHog eval POC...")  # noqa: T201

            matrix = HedgeboxMatrix(
                seed="b1ef3c66-5f43-488a-98be-6b46d92fbcef",
                days_past=120,
                days_future=30,
                n_clusters=500,
                group_type_index_offset=0,
            )
            matrix_manager = MatrixManager(matrix, print_steps=True)
            with override_settings(TEST=False):
                org, team, user = matrix_manager.ensure_account_and_save(
                    f"eval-{today.isoformat()}",
                    EVAL_USER_FULL_NAME,
                    "Hedgebox Inc.",
                )
        else:
            print("Using existing demo data for PostHog eval POC...")  # noqa: T201
            org = team.organization
            membership = org.memberships.first()
            assert membership is not None
            user = membership.user

        yield org, team, user


@pytest.fixture(scope="session", autouse=True)
def core_memory(demo_org_team_user, django_db_blocker) -> Generator[CoreMemory, None, None]:
    initial_memory = """Hedgebox is a cloud storage service enabling users to store, share, and access files across devices.

    The company operates in the cloud storage and collaboration market for individuals and businesses.

    Their audience includes professionals and organizations seeking file management and collaboration solutions.

    Hedgebox's freemium model provides free accounts with limited storage and paid subscription plans for additional features.

    Core features include file storage, synchronization, sharing, and collaboration tools for seamless file access and sharing.

    It integrates with third-party applications to enhance functionality and streamline workflows.

    Hedgebox sponsors the YouTube channel Marius Tech Tips."""

    with django_db_blocker.unblock():
        memory, _ = CoreMemory.objects.get_or_create(
            team=demo_org_team_user[1],
            defaults={
                "text": initial_memory,
                "initial_text": initial_memory,
                "scraping_status": CoreMemory.ScrapingStatus.COMPLETED,
            },
        )
    yield memory

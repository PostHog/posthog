import datetime
from collections.abc import Generator
import os
from pathlib import Path
from collections.abc import Sequence
from braintrust_langchain import BraintrustCallbackHandler, set_global_handler
from braintrust import Eval, init_logger
from braintrust.framework import EvalData, EvalTask, EvalScorer, Input, Output
from django.conf import settings
import pytest
from django.test import override_settings

from ee.models.assistant import CoreMemory
from posthog.demo.matrix.manager import MatrixManager
from posthog.models import Team
from posthog.tasks.demo_create_data import HedgeboxMatrix

# We want the PostHog django_db_setup fixture here
from posthog.conftest import django_db_setup  # noqa: F401

handler = BraintrustCallbackHandler()
set_global_handler(handler)


def MaxEval(
    experiment_name: str,
    data: EvalData[Input, Output],
    task: EvalTask[Input, Output],
    scores: Sequence[EvalScorer[Input, Output]],
):
    # We need to specify a separate project for each MaxEval() suite for comparison to baseline to work
    # That's the way Braintrust folks recommended - Braintrust projects are much more lightweight than PostHog ones
    project_name = f"max-ai-{experiment_name}"
    init_logger(project_name)
    result = Eval(
        project_name,
        data=data,
        task=task,
        scores=scores,
        trial_count=3 if os.getenv("CI") else 1,
    )
    if os.getenv("GITHUB_EVENT_NAME") == "pull_request":
        with open("eval_results.jsonl", "a") as f:
            f.write(result.summary.as_json() + "\n")
    return result


@pytest.fixture(scope="package")
def demo_org_team_user(django_db_setup, django_db_blocker):  # noqa: F811
    with django_db_blocker.unblock():
        should_create_new_team = True
        team = Team.objects.order_by("-created_at").first()
        if team and team.created_at.date() >= datetime.date.today():
            should_create_new_team = False  # Project doesn't exist or is from yesterday, let's get a new one

        if should_create_new_team:
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
                org, team, user = matrix_manager.ensure_account_and_save(
                    "eval@posthog.com", "Eval Doe", "Hedgebox Inc."
                )
        else:
            print(f"Using existing demo data for evals...")  # noqa: T201
            org = team.organization
            user = org.memberships.first().user

        yield org, team, user


@pytest.fixture(scope="package")
def core_memory(demo_org_team_user, django_db_blocker) -> Generator[CoreMemory, None, None]:
    initial_memory = """Hedgebox is a cloud storage service enabling users to store, share, and access files across devices.

    The company operates in the cloud storage and collaboration market for individuals and businesses.

    Their audience includes professionals and organizations seeking file management and collaboration solutions.

    Hedgebox’s freemium model provides free accounts with limited storage and paid subscription plans for additional features.

    Core features include file storage, synchronization, sharing, and collaboration tools for seamless file access and sharing.

    It integrates with third-party applications to enhance functionality and streamline workflows.

    Hedgebox sponsors the YouTube channel Marius Tech Tips."""

    with django_db_blocker.unblock():
        core_memory, _ = CoreMemory.objects.get_or_create(
            team=demo_org_team_user[1],
            text=initial_memory,
            initial_text=initial_memory,
            scraping_status=CoreMemory.ScrapingStatus.COMPLETED,
        )
    yield core_memory


# TODO: Remove below `pytest_collection_modifyitems` with `skipif` injection once deepeval is refactored away,
#       because newer braintrust-based structure uses a different prefix for test files (eval_*.py)


def pytest_collection_modifyitems(items):
    current_dir = Path(__file__).parent
    for item in items:
        if Path(item.fspath).is_relative_to(current_dir):
            item.add_marker(
                pytest.mark.skipif(not settings.IN_EVAL_TESTING, reason="Only runs for the assistant evaluation")
            )

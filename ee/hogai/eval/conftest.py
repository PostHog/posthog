import datetime
import os
from collections import namedtuple
from collections.abc import Generator, Sequence
from unittest import mock

import pytest
from _pytest.terminal import TerminalReporter
from braintrust import EvalAsync, init_logger
from braintrust.framework import EvalData, EvalScorer, EvalTask, Input, Output
from braintrust_langchain import BraintrustCallbackHandler, set_global_handler
from django.test import override_settings

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.eval.scorers import PlanAndQueryOutput
from ee.hogai.graph.graph import AssistantGraph, InsightsAssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation, CoreMemory

# We want the PostHog django_db_setup fixture here
from posthog.conftest import django_db_setup  # noqa: F401
from posthog.demo.matrix.manager import MatrixManager
from posthog.models import Team
from posthog.schema import HumanMessage, VisualizationMessage
from posthog.tasks.demo_create_data import HedgeboxMatrix

handler = BraintrustCallbackHandler()
if os.environ.get("BRAINTRUST_API_KEY"):
    set_global_handler(handler)


async def MaxEval(
    experiment_name: str,
    data: EvalData[Input, Output],
    task: EvalTask[Input, Output],
    scores: Sequence[EvalScorer[Input, Output]],
):
    # We need to specify a separate project for each MaxEval() suite for comparison to baseline to work
    # That's the way Braintrust folks recommended - Braintrust projects are much more lightweight than PostHog ones
    project_name = f"max-ai-{experiment_name}"
    init_logger(project_name)
    result = await EvalAsync(
        project_name,
        data=data,
        task=task,
        scores=scores,
        trial_count=3 if os.getenv("CI") else 1,
        timeout=60 * 5,
        is_public=True,
    )
    if os.getenv("GITHUB_EVENT_NAME") == "pull_request":
        with open("eval_results.jsonl", "a") as f:
            f.write(result.summary.as_json() + "\n")
    return result


@pytest.fixture
def call_root_for_insight_generation(demo_org_team_user):
    # This graph structure will first get a plan, then generate the SQL query.

    insights_subgraph = (
        # Insights subgraph without query execution, so we only create the queries
        InsightsAssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_query_creation_flow(next_node=AssistantNodeName.END)
        .compile()
    )
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            path_map={
                "insights": AssistantNodeName.INSIGHTS_SUBGRAPH,
                "root": AssistantNodeName.END,
                "search_documentation": AssistantNodeName.END,
                "memory_onboarding": AssistantNodeName.END,
                "end": AssistantNodeName.END,
            }
        )
        .add_node(AssistantNodeName.INSIGHTS_SUBGRAPH, insights_subgraph)
        .add_edge(AssistantNodeName.INSIGHTS_SUBGRAPH, AssistantNodeName.END)
        # TRICKY: We need to set a checkpointer here because async tests create a new event loop.
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(query: str) -> PlanAndQueryOutput:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        # Initial state for the graph
        initial_state = AssistantState(
            messages=[HumanMessage(content=f"Answer this question: {query}")],
        )

        # Invoke the graph. The state will be updated through planner and then generator.
        final_state_raw = await graph.ainvoke(
            initial_state,
            {"configurable": {"thread_id": conversation.id}},
        )

        final_state = AssistantState.model_validate(final_state_raw)

        if not final_state.messages or not isinstance(final_state.messages[-1], VisualizationMessage):
            return {
                "plan": None,
                "query": None,
                "query_generation_retry_count": final_state.query_generation_retry_count,
            }
        return {
            "plan": final_state.messages[-1].plan,
            "query": final_state.messages[-1].answer,
            "query_generation_retry_count": final_state.query_generation_retry_count,
        }

    return callable


@pytest.fixture(scope="package")
def demo_org_team_user(django_db_setup, django_db_blocker):  # noqa: F811
    with django_db_blocker.unblock():
        team = Team.objects.order_by("-created_at").first()
        today = datetime.date.today()
        # If there's no eval team or it's older than today, we need to create a new one with fresh data
        should_create_new_team = not team or team.created_at.date() < today

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
                    f"eval-{today.isoformat()}", "Eval Doe", "Hedgebox Inc."
                )
        else:
            print(f"Using existing demo data for evals...")  # noqa: T201
            org = team.organization
            user = org.memberships.first().user

        yield org, team, user


@pytest.fixture(scope="package", autouse=True)
def core_memory(demo_org_team_user, django_db_blocker) -> Generator[CoreMemory, None, None]:
    initial_memory = """Hedgebox is a cloud storage service enabling users to store, share, and access files across devices.

    The company operates in the cloud storage and collaboration market for individuals and businesses.

    Their audience includes professionals and organizations seeking file management and collaboration solutions.

    Hedgebox's freemium model provides free accounts with limited storage and paid subscription plans for additional features.

    Core features include file storage, synchronization, sharing, and collaboration tools for seamless file access and sharing.

    It integrates with third-party applications to enhance functionality and streamline workflows.

    Hedgebox sponsors the YouTube channel Marius Tech Tips."""

    with django_db_blocker.unblock():
        core_memory, _ = CoreMemory.objects.get_or_create(
            team=demo_org_team_user[1],
            defaults={
                "text": initial_memory,
                "initial_text": initial_memory,
                "scraping_status": CoreMemory.ScrapingStatus.COMPLETED,
            },
        )
    yield core_memory


_nodeid_to_results_url_map: dict[str, str] = {}
"""Map of test nodeid (file + test name) to Braintrust results URL."""


@pytest.fixture(autouse=True)
def capture_stdout(request, capsys):
    yield
    captured = capsys.readouterr()
    if "See results for " in captured.out:
        # Get only the line with the results link. The output we are extracting from is something like this:
        # [...]
        # 0.00$ (-00.02%) 'estimated_cost'        (4 improvements, 3 regressions)
        # See results for braintrust-more-evals-1747934384 at https://www.braintrust.dev/app/PostHog/p/max-ai-memory/experiments/braintrust-more-evals-1747934384
        # Experiment braintrust-more-evals-1747934384 is running at https://www.braintrust.dev/app/PostHog/p/max-ai-memory/experiments/braintrust-more-evals-1747934384
        # [...]
        results_url = next(line for line in captured.out.split("\n") if "See results for " in line).split(" at ")[1]
        _nodeid_to_results_url_map[request.node.nodeid] = results_url


class BraintrustURLReporter(TerminalReporter):  # type: ignore
    """
    Our reporter adds one feature to the default one: for each passed eval_ test, it adds a link to the Braintrust results.
    By default, passed tests don't get any short summary, but we can override that - which is what we do here.
    """

    # No idea what type report.longrepr or report.longrrepr.reprcrash _should_ be, but this works
    DummyLongRepr = namedtuple("DummyLongRepr", ["reprcrash"])
    DummyReprCrash = namedtuple("DummyReprCrash", ["message"])

    def short_test_summary(self):
        for report in self.stats.get("passed", []):
            report.longrepr = self.DummyLongRepr(
                reprcrash=self.DummyReprCrash(
                    message=_nodeid_to_results_url_map.get(report.nodeid, f"No Braintrust results for {report.nodeid}")
                )
            )
        with mock.patch("_pytest.terminal.running_on_ci", return_value=True):
            # Make pytest think we're running in CI, because annoyingly _pytest.terminal._get_line_with_reprcrash_message
            # trims the short test summary (i.e. Braintrust URL) terminal width if it thinks we're not in CI
            super().short_test_summary()


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    if not str(config.rootdir).endswith("/ee/hogai/eval"):
        return  # No-op if not running specifically evals
    # Register a custom reporter that adds a link to the Braintrust results
    vanilla_reporter = config.pluginmanager.getplugin("terminalreporter")
    braintrust_url_reporter = BraintrustURLReporter(config)
    config.pluginmanager.unregister(vanilla_reporter)
    config.pluginmanager.register(braintrust_url_reporter, "terminalreporter")

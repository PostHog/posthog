import os
import datetime
from collections.abc import Generator

import pytest

from django.test import override_settings

from braintrust_langchain import BraintrustCallbackHandler, set_global_handler
from langchain_core.runnables import RunnableConfig

from posthog.schema import FailureMessage, HumanMessage

from posthog.demo.matrix.manager import MatrixManager
from posthog.models import Dashboard, DashboardTile, Insight, Organization, Team, User
from posthog.tasks.demo_create_data import HedgeboxMatrix

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.artifacts.utils import unwrap_visualization_artifact_content
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer

# We want the PostHog set_up_evals fixture here
from ee.hogai.eval.conftest import set_up_evals  # noqa: F401
from ee.hogai.eval.scorers import PlanAndQueryOutput
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage
from ee.models.assistant import Conversation, CoreMemory

handler = BraintrustCallbackHandler()
if os.environ.get("BRAINTRUST_API_KEY") and os.environ.get("EVAL_MODE") != "offline":
    set_global_handler(handler)


EVAL_USER_FULL_NAME = "Karen Smith"


@pytest.fixture
def call_root_for_insight_generation(demo_org_team_user):
    # This graph structure will first get a plan, then generate the SQL query.
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root()
        # TRICKY: We need to set a checkpointer here because async tests create a new event loop.
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(
        query_with_extra_context: str | tuple[str, str],
    ) -> PlanAndQueryOutput:
        # If query_with_extra_context is a tuple, the first element is the query, the second is the extra context
        # in case there's an ask_user tool call.
        query = query_with_extra_context[0] if isinstance(query_with_extra_context, tuple) else query_with_extra_context
        # Initial state for the graph
        initial_state = AssistantState(
            messages=[HumanMessage(content=f"Answer this question: {query}")],
        )
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

        # Invoke the graph. The state will be updated through planner and then generator.
        config = RunnableConfig(configurable={"thread_id": conversation.id})
        final_state_raw = await graph.ainvoke(initial_state, config)

        final_state = AssistantState.model_validate(final_state_raw)

        # If we have extra context for the potential ask_user tool, and there's no message of type ai/failure
        # or artifact, we should answer with that extra context. We only do this once at most in an eval case.
        if isinstance(query_with_extra_context, tuple) and not any(
            isinstance(m, ArtifactRefMessage | FailureMessage) for m in final_state.messages
        ):
            final_state.messages = [
                *final_state.messages,
                HumanMessage(content=query_with_extra_context[1]),
            ]
            final_state.graph_status = "resumed"
            final_state_raw = await graph.ainvoke(final_state, config)
            final_state = AssistantState.model_validate(final_state_raw)

        # The order is a viz message, tool call message, and assistant message.
        if (
            not final_state.messages
            or not len(final_state.messages) >= 3
            or not isinstance(final_state.messages[-3], ArtifactRefMessage)
        ):
            return {
                "plan": None,
                "query": None,
                "query_generation_retry_count": final_state.query_generation_retry_count,
            }

        artifact_manager = ArtifactManager(team=demo_org_team_user[1], user=demo_org_team_user[2], config=config)
        enriched_message = await artifact_manager.aenrich_message(final_state.messages[-3])
        content = unwrap_visualization_artifact_content(enriched_message)
        if content is None:
            return {
                "plan": None,
                "query": None,
                "query_generation_retry_count": final_state.query_generation_retry_count,
            }
        return {
            "plan": content.description,
            "query": content.query,
            "query_generation_retry_count": final_state.query_generation_retry_count,
        }

    yield callable


@pytest.fixture(scope="session", autouse=True)
def demo_org_team_user(
    set_up_evals,  # noqa: F811
    django_db_blocker,
) -> Generator[tuple[Organization, Team, User], None, None]:
    with django_db_blocker.unblock():
        team: Team | None = Team.objects.order_by("-created_at").first()
        today = datetime.date.today()
        # If there's no eval team or it's older than today, we need to create a new one with fresh data
        if not team or team.created_at.date() < today:
            print("Generating fresh demo data for evals...")  # noqa: T201

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
                    f"eval-{today.isoformat()}", EVAL_USER_FULL_NAME, "Hedgebox Inc."
                )
        else:
            print("Using existing demo data for evals...")  # noqa: T201
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
        core_memory, _ = CoreMemory.objects.get_or_create(
            team=demo_org_team_user[1],
            defaults={
                "text": initial_memory,
                "initial_text": initial_memory,
                "scraping_status": CoreMemory.ScrapingStatus.COMPLETED,
            },
        )
    yield core_memory


class DashboardWithInsightsFixture:
    """Container for dashboard with insights fixture data."""

    def __init__(
        self,
        dashboard: Dashboard,
        insight_dau: Insight,
        insight_funnel: Insight,
        insight_retention: Insight,
        insight_wau: Insight,
    ):
        self.dashboard = dashboard
        self.insight_dau = insight_dau
        self.insight_funnel = insight_funnel
        self.insight_retention = insight_retention
        self.insight_wau = insight_wau

    @property
    def insights(self) -> dict[str, Insight]:
        return {
            "dau": self.insight_dau,
            "funnel": self.insight_funnel,
            "retention": self.insight_retention,
        }

    @property
    def replacement(self) -> Insight:
        return self.insight_wau

    def get_dashboard_context(self, include_wau_insight: bool = False) -> dict:
        """Get the dashboard context dict for injection into tool config.

        Args:
            include_wau_insight: If True, include WAU insight in the dashboard (for testing replacement scenarios).
        """
        insights = [
            {
                "id": self.insight_dau.id,
                "short_id": self.insight_dau.short_id,
                "name": self.insight_dau.name,
            },
            {
                "id": self.insight_funnel.id,
                "short_id": self.insight_funnel.short_id,
                "name": self.insight_funnel.name,
            },
            {
                "id": self.insight_retention.id,
                "short_id": self.insight_retention.short_id,
                "name": self.insight_retention.name,
            },
        ]

        # For replacement scenarios, include the WAU insight as a known insight
        # (simulating it was previously created and is available)
        if include_wau_insight:
            insights.append(
                {
                    "id": self.insight_wau.id,
                    "short_id": self.insight_wau.short_id,
                    "name": self.insight_wau.name,
                }
            )

        return {
            "id": self.dashboard.id,
            "name": self.dashboard.name,
            "insights": insights,
        }


@pytest.fixture
def dashboard_with_insights(
    demo_org_team_user,
) -> Generator[DashboardWithInsightsFixture, None, None]:
    """Creates a dashboard with 3 insights and 1 replacement insight for testing UpsertDashboardTool."""
    org, team, user = demo_org_team_user

    # Create insights that will be on the dashboard
    insight_dau = Insight.objects.create(
        team=team,
        name="Daily Active Users",
        description="Shows daily active users over time",
        saved=True,
        created_by=user,
        query={
            "kind": "TrendsQuery",
            "series": [{"event": "$pageview", "kind": "EventsNode"}],
        },
    )

    insight_funnel = Insight.objects.create(
        team=team,
        name="Signup Funnel",
        description="Conversion funnel from visit to signup",
        saved=True,
        created_by=user,
        query={
            "kind": "FunnelsQuery",
            "series": [
                {"event": "$pageview", "kind": "EventsNode"},
                {"event": "signed_up", "kind": "EventsNode"},
            ],
        },
    )

    insight_retention = Insight.objects.create(
        team=team,
        name="User Retention",
        description="User retention cohort analysis",
        saved=True,
        created_by=user,
        query={
            "kind": "RetentionQuery",
            "retentionFilter": {"period": "Week"},
        },
    )

    # Create the dashboard
    dashboard = Dashboard.objects.create(
        team=team,
        name="Growth Dashboard",
        description="Dashboard for tracking growth metrics",
        created_by=user,
    )

    # Add tiles to dashboard
    DashboardTile.objects.create(
        dashboard=dashboard,
        insight=insight_dau,
        layouts={"lg": {"x": 0, "y": 0, "w": 6, "h": 4}},
    )
    DashboardTile.objects.create(
        dashboard=dashboard,
        insight=insight_funnel,
        layouts={"lg": {"x": 6, "y": 0, "w": 6, "h": 4}},
    )
    DashboardTile.objects.create(
        dashboard=dashboard,
        insight=insight_retention,
        layouts={"lg": {"x": 0, "y": 4, "w": 6, "h": 4}},
    )

    # Create replacement insight (not on dashboard yet)
    insight_wau = Insight.objects.create(
        team=team,
        name="Weekly Active Users",
        description="Shows weekly active users over time",
        saved=True,
        created_by=user,
        query={
            "kind": "TrendsQuery",
            "series": [{"event": "$pageview", "kind": "EventsNode"}],
            "interval": "week",
        },
    )

    yield DashboardWithInsightsFixture(
        dashboard=dashboard,
        insight_dau=insight_dau,
        insight_funnel=insight_funnel,
        insight_retention=insight_retention,
        insight_wau=insight_wau,
    )
    # No manual cleanup needed - Django's test framework handles rollback automatically

"""Shared data setup functions for eval harnesses.

Extracted from ``ee/hogai/eval/ci/conftest.py`` so both CI evals and sandboxed
agent evals can reuse the same demo data creation logic.
"""

from __future__ import annotations

import datetime

from django.test import override_settings

from posthog.demo.matrix.manager import MatrixManager
from posthog.models import Dashboard, DashboardTile, Insight, Organization, Team, User
from posthog.tasks.demo_create_data import HedgeboxMatrix

from ee.models.assistant import CoreMemory

EVAL_USER_FULL_NAME = "Karen Smith"


def create_demo_org_team_user(django_db_blocker) -> tuple[Organization, Team, User]:
    """Create or reuse HedgeboxMatrix demo data for evals.

    Uses a deterministic seed so demo data is consistent across runs.
    If a team already exists from today, it is reused. Otherwise fresh
    data is generated via ``HedgeboxMatrix`` with 500 clusters and 120 days
    of history.
    """
    with django_db_blocker.unblock():
        team: Team | None = Team.objects.order_by("-created_at").first()
        today = datetime.date.today()
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

    return org, team, user


def create_core_memory(team: Team, django_db_blocker) -> CoreMemory:
    """Create or get the core memory for a team."""
    initial_memory = """Hedgebox is a cloud storage service enabling users to store, share, and access files across devices.

    The company operates in the cloud storage and collaboration market for individuals and businesses.

    Their audience includes professionals and organizations seeking file management and collaboration solutions.

    Hedgebox's freemium model provides free accounts with limited storage and paid subscription plans for additional features.

    Core features include file storage, synchronization, sharing, and collaboration tools for seamless file access and sharing.

    It integrates with third-party applications to enhance functionality and streamline workflows.

    Hedgebox sponsors the YouTube channel Marius Tech Tips."""

    with django_db_blocker.unblock():
        core_memory, _ = CoreMemory.objects.get_or_create(
            team=team,
            defaults={
                "text": initial_memory,
                "initial_text": initial_memory,
                "scraping_status": CoreMemory.ScrapingStatus.COMPLETED,
            },
        )
    return core_memory


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


def create_dashboard_with_insights(
    org: Organization,
    team: Team,
    user: User,
) -> DashboardWithInsightsFixture:
    """Create a dashboard with 3 insights and 1 replacement insight for testing."""
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

    return DashboardWithInsightsFixture(
        dashboard=dashboard,
        insight_dau=insight_dau,
        insight_funnel=insight_funnel,
        insight_retention=insight_retention,
        insight_wau=insight_wau,
    )

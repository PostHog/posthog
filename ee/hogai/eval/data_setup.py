"""Shared data setup functions for eval harnesses.

Extracted from ``ee/hogai/eval/ci/conftest.py`` so both CI evals and sandboxed
agent evals can reuse the same demo data creation logic.
"""

from __future__ import annotations

import uuid
import logging
import datetime

from django.db import transaction
from django.test import override_settings

from posthog.clickhouse.client import sync_execute
from posthog.demo.matrix.manager import MatrixManager
from posthog.models import GroupTypeMapping, Insight, Organization, OrganizationMembership, Team, User
from posthog.models.event.sql import COPY_EVENTS_BETWEEN_TEAMS
from posthog.models.group.sql import COPY_GROUPS_BETWEEN_TEAMS
from posthog.models.person.sql import COPY_PERSON_DISTINCT_ID2S_BETWEEN_TEAMS, COPY_PERSONS_BETWEEN_TEAMS
from posthog.tasks.demo_create_data import HedgeboxMatrix

from products.dashboards.backend.models import Dashboard, DashboardTile

from ee.models.assistant import CoreMemory

logger = logging.getLogger(__name__)

EVAL_SEED = "b1ef3c66-5f43-488a-98be-6b46d92fbcef"
EVAL_USER_FULL_NAME = "Karen Smith"

MASTER_ORG_NAME = "Hedgebox Master Seed"
MASTER_USER_EMAIL = "eval-master-seed@posthog.test"


def _build_hedgebox_matrix() -> HedgeboxMatrix:
    return HedgeboxMatrix(
        seed=EVAL_SEED,
        days_past=120,
        days_future=30,
        n_clusters=500,
        group_type_index_offset=0,
    )


def create_isolated_demo_data(
    django_db_blocker,
    *,
    label: str,
) -> tuple[Organization, Team, User]:
    """Create an isolated org/team/user with HedgeboxMatrix demo data.

    Uses ``use_pre_save=True`` so the simulation runs once (stored in
    master team 0) and subsequent calls for different labels only copy
    ClickHouse data via server-side SQL — much faster than re-simulating
    and re-ingesting via Kafka.

    Each *label* produces a separate ``Organization`` so eval harnesses
    don't interfere with each other.
    """
    org_name = f"Hedgebox Inc. ({label})"
    today = datetime.date.today()
    email = f"eval-{label}-{today.isoformat()}@posthog.test"

    with django_db_blocker.unblock():
        # Check for existing data from today
        existing_org = Organization.objects.filter(name=org_name).order_by("-created_at").first()
        if existing_org and existing_org.created_at.date() == today:
            logger.info("Using existing demo data for %r", label)
            team = existing_org.teams.first()
            assert team is not None
            membership = existing_org.memberships.first()
            assert membership is not None
            user = membership.user
            if "@" not in (user.email or ""):
                user.email = email
                user.save(update_fields=["email"])
            return existing_org, team, user

        logger.info("Generating demo data for %r", label)
        matrix_manager = MatrixManager(_build_hedgebox_matrix(), use_pre_save=True, print_steps=True)
        with override_settings(TEST=False):
            # Simulation saving should occur in non-test mode, so that Kafka isn't mocked.
            # Normally in tests we don't want to ingest via Kafka, but simulation saving is
            # specifically designed to use that route for speed.
            org, team, user = matrix_manager.ensure_account_and_save(email, EVAL_USER_FULL_NAME, org_name)

    return org, team, user


def create_demo_org_team_user(django_db_blocker) -> tuple[Organization, Team, User]:
    """Create or reuse demo data for CI evals. Thin wrapper for backward compat."""
    return create_isolated_demo_data(django_db_blocker, label="ci")


def ensure_master_demo_team(django_db_blocker) -> int:
    """Ensure a master Hedgebox demo team exists with events in both PSQL and CH.

    Reuses the master team across sessions when it has CH events. Rebuilds from
    scratch when either side is empty. Returns the master team id (autoincrement,
    not ``MatrixManager.MASTER_TEAM_ID`` — we own this team's lifecycle).
    """

    with django_db_blocker.unblock():
        existing_org = Organization.objects.filter(name=MASTER_ORG_NAME).order_by("-created_at").first()
        if existing_org is not None:
            team = existing_org.teams.first()
            if team is not None:
                ch_event_count = sync_execute(
                    "SELECT count() FROM events WHERE team_id = %(team_id)s",
                    {"team_id": team.id},
                )[0][0]
                if ch_event_count > 0:
                    logger.info("Reusing master demo team id=%d (events=%d)", team.id, ch_event_count)
                    return team.id
                logger.warning("Master demo team id=%d has no CH events — regenerating", team.id)
            User.objects.filter(organization_membership__organization=existing_org).delete()
            existing_org.delete()
            User.objects.filter(email=MASTER_USER_EMAIL).delete()

        User.objects.filter(email=MASTER_USER_EMAIL, organization_membership__isnull=True).delete()

        logger.info("Generating master demo team")
        # use_pre_save=False: we are the master — save simulation directly to this team
        # without going through MatrixManager._is_demo_data_pre_saved (which only checks PSQL
        # and lies when CH has been wiped independently).
        matrix_manager = MatrixManager(_build_hedgebox_matrix(), use_pre_save=False, print_steps=True)
        with override_settings(TEST=False):
            _org, team, _user = matrix_manager.ensure_account_and_save(
                MASTER_USER_EMAIL, EVAL_USER_FULL_NAME, MASTER_ORG_NAME
            )
        return team.id


def copy_demo_data_to_new_team(
    master_team_id: int,
    django_db_blocker,
    *,
    label: str,
) -> tuple[Organization, Team, User]:
    """Create a fresh org/team/user and copy master's demo data into it.

    Copies CH rows (persons, distinct_ids, events, groups) via server-side
    ``INSERT ... SELECT`` SQL, mirrors ``GroupTypeMapping`` rows into the new
    project, backfills PSQL persons from CH, and runs
    ``HedgeboxMatrix.set_project_up`` on the new team so it gets the usual
    actions, cohorts, and feature flags.
    """

    suffix = uuid.uuid4().hex[:8]
    org_name = f"Hedgebox ({label}-{suffix})"
    email = f"eval-{label}-{suffix}@posthog.test"

    with django_db_blocker.unblock():
        master_team = Team.objects.get(id=master_team_id)

        with transaction.atomic():
            org = Organization.objects.create(name=org_name)
            user = User.objects.create_and_join(
                org,
                email,
                None,
                EVAL_USER_FULL_NAME,
                OrganizationMembership.Level.ADMIN,
                theme_mode="system",
                role_at_organization="engineering",
            )
            team = Team.objects.create(
                organization=org,
                ingested_event=True,
                completed_snippet_onboarding=True,
                is_demo=True,
            )

        copy_params = {"source_team_id": master_team_id, "target_team_id": team.id}
        sync_execute(COPY_PERSONS_BETWEEN_TEAMS, copy_params)
        sync_execute(COPY_PERSON_DISTINCT_ID2S_BETWEEN_TEAMS, copy_params)
        sync_execute(COPY_EVENTS_BETWEEN_TEAMS, copy_params)
        sync_execute(COPY_GROUPS_BETWEEN_TEAMS, copy_params)

        GroupTypeMapping.objects.filter(project_id=team.project_id).delete()
        GroupTypeMapping.objects.bulk_create(
            GroupTypeMapping(team_id=team.id, project_id=team.project_id, **record)
            for record in GroupTypeMapping.objects.filter(project_id=master_team.project_id).values(
                "group_type", "group_type_index", "name_singular", "name_plural"
            )
        )

        MatrixManager._sync_postgres_with_clickhouse_data(master_team_id, team.id)

        with override_settings(TEST=False):
            _build_hedgebox_matrix().set_project_up(team, user)

        team.save()
        team.project.save()

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

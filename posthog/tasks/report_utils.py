import dataclasses
from datetime import datetime
from typing import Any, Optional, Union, cast

from django.conf import settings

import structlog
from dateutil import parser
from posthoganalytics.client import Client

from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.utils import get_machine_id

logger = structlog.get_logger(__name__)


def get_org_owner_or_first_user(organization_id: str) -> Optional[User]:
    # Find the membership object for the org owner
    user = None
    membership = OrganizationMembership.objects.filter(
        organization_id=organization_id, level=OrganizationMembership.Level.OWNER
    ).first()
    if not membership:
        # If no owner membership is present, pick the first membership association we can find
        membership = OrganizationMembership.objects.filter(organization_id=organization_id).first()
    if hasattr(membership, "user"):
        membership = cast(OrganizationMembership, membership)
        user = membership.user
    else:
        capture_exception(
            Exception("No user found for org while generating report"),
            {"org": {"organization_id": organization_id}},
        )
    return user


def capture_event(
    *,
    pha_client: Client,
    name: str,
    organization_id: Optional[str] = None,
    team_id: Optional[int] = None,
    properties: dict[str, Any],
    timestamp: Optional[Union[datetime, str]] = None,
    distinct_id: Optional[str] = None,
) -> None:
    """
    Captures a single event.
    """
    if timestamp and isinstance(timestamp, str):
        try:
            timestamp = parser.isoparse(timestamp)
        except ValueError:
            timestamp = None

    if not organization_id and not team_id:
        raise ValueError("Either organization_id or team_id must be provided")

    if not distinct_id:
        if not organization_id:
            team = Team.objects.get(id=team_id)
            organization_id = str(team.organization_id)
        org_owner = get_org_owner_or_first_user(organization_id)
        distinct_id = org_owner.distinct_id if org_owner and org_owner.distinct_id else f"org-{organization_id}"

    if is_cloud():
        pha_client.capture(
            distinct_id=distinct_id,
            event=name,
            properties={**properties, "scope": "user"},
            groups={"organization": str(organization_id), "instance": settings.SITE_URL},
            timestamp=timestamp,
        )
    else:
        pha_client.capture(
            distinct_id=get_machine_id(),
            event=name,
            properties={**properties, "scope": "machine"},
            groups={"instance": settings.SITE_URL},
            timestamp=timestamp,
        )


@dataclasses.dataclass
class TeamDigestReport:
    team_id: int
    team_name: str
    report: dict[str, Any]
    digest_items_with_data: int


@dataclasses.dataclass
class OrgDigestReport:
    organization_id: str
    organization_name: str
    organization_created_at: str
    teams: list[TeamDigestReport]
    total_digest_items_with_data: int

    def filter_for_user(self, user_teams: set[int], user_notification_teams: set[int]) -> "OrgDigestReport":
        """Returns a new OrgDigestReport with only the teams the user has access to and notifications enabled for"""
        filtered_teams = [
            team_report
            for team_report in self.teams
            if team_report.team_id in user_teams and team_report.team_id in user_notification_teams
        ]
        return OrgDigestReport(
            organization_id=self.organization_id,
            organization_name=self.organization_name,
            organization_created_at=self.organization_created_at,
            teams=filtered_teams,
            total_digest_items_with_data=sum(team_report.digest_items_with_data for team_report in filtered_teams),
        )


def get_user_team_lookup(organization_id: str) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    """
    Returns (user_team_access, user_notification_prefs) where:
    - user_team_access maps user_id -> set of team_ids they have access to
    - user_notification_prefs maps user_id -> set of team_ids where notifications are enabled
    """
    from posthog.models.organization import Organization
    from posthog.tasks.email import NotificationSetting, should_send_notification

    org = Organization.objects.prefetch_related(
        "teams", "teams__explicit_memberships__parent_membership__user", "memberships__user"
    ).get(id=organization_id)

    user_teams: dict[int, set[int]] = {}
    user_notifications: dict[int, set[int]] = {}

    # Build lookup of team access
    for team in org.teams.all():
        for user in team.all_users_with_access():
            if user.id not in user_teams:
                user_teams[user.id] = set()
                user_notifications[user.id] = set()
            user_teams[user.id].add(team.id)
            # Check notification preferences
            if should_send_notification(user, NotificationSetting.WEEKLY_PROJECT_DIGEST.value, team.id):
                user_notifications[user.id].add(team.id)

    return user_teams, user_notifications

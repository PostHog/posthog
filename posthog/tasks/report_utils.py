from datetime import datetime
from typing import Any, Optional, Union, cast

import structlog
from dateutil import parser
from django.conf import settings
from posthoganalytics.client import Client
from sentry_sdk import capture_exception

from posthog.cloud_utils import is_cloud
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
            distinct_id,
            name,
            {**properties, "scope": "user"},
            groups={"organization": organization_id, "instance": settings.SITE_URL},
            timestamp=timestamp,
        )
    else:
        pha_client.capture(
            get_machine_id(),
            name,
            {**properties, "scope": "machine"},
            groups={"instance": settings.SITE_URL},
            timestamp=timestamp,
        )

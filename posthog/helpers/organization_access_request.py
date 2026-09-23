import datetime
from typing import Any, Optional

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import Organization


@frozen
class OrganizationAccessRequest:
    email: str
    organization: Organization


class OrganizationAccessRequestGrant:
    """
    A short-lived permission to ask one organization's admins for access.

    A person who is turned away because another organization owns their email domain has no
    account, so the request-access endpoint cannot authenticate them. The identity provider has
    already proved they control the address at that point, so the login pipeline records the
    address and the owning organization in their session, and the endpoint reads them from there.
    The client never names either one, which stops an anonymous caller from mailing the admins of
    an organization they picked, under an address they do not own.
    """

    SESSION_KEY = "organization_access_request"
    # The grant covers the click that follows the blocked login, not a later visit.
    TTL = datetime.timedelta(hours=1)

    @staticmethod
    def build(email: str, organization: Organization) -> dict[str, str]:
        return {
            "email": email,
            "organization_id": str(organization.id),
            "granted_at": timezone.now().isoformat(),
        }

    @staticmethod
    def take(session: Any) -> Optional[OrganizationAccessRequest]:
        """Remove the grant from the session and resolve it, so one blocked login sends one email."""
        grant = session.pop(OrganizationAccessRequestGrant.SESSION_KEY, None)
        if not isinstance(grant, dict):
            return None

        try:
            granted_at = datetime.datetime.fromisoformat(grant["granted_at"])
            email = grant["email"]
            organization_id = grant["organization_id"]
        except (KeyError, TypeError, ValueError):
            return None

        if timezone.now() - granted_at > OrganizationAccessRequestGrant.TTL:
            return None

        organization = Organization.objects.filter(id=organization_id).first()
        if organization is None:
            return None

        return OrganizationAccessRequest(email=email, organization=organization)

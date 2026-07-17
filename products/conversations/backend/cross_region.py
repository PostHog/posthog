"""Cross-region org-membership verification for Conversations Slack enrichment.

PostHog's support desk runs on US Cloud, but its Slack support channels serve
customers whose PostHog organizations live in either region. The enrichment can
only see ``OrganizationMembership`` rows for its own region, so it cannot verify
attribution for a customer registered in the sibling region. This module lets a
run confirm such an org by asking the other region — which holds the membership —
over an HMAC-signed server-to-server call, the same pattern as the Slack app's
cross-region workspace probe (``products/slack_app/backend/api.py``).
"""

import hmac
import json
import time
import hashlib
from dataclasses import asdict, dataclass

from django.conf import settings

import requests
import structlog

from posthog.models.organization import OrganizationMembership
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

CROSS_REGION_SIGNATURE_HEADER = "X-PostHog-Conversations-Signature"
CROSS_REGION_TIMESTAMP_HEADER = "X-PostHog-Conversations-Timestamp"
# Fast connect failure; the receiver runs a single indexed membership query.
CROSS_REGION_TIMEOUT_SECONDS = (3, 10)
# Bound each probe body so a batch of pure sibling-region customers can't build one
# oversized request; larger inputs fan out across several calls.
CROSS_REGION_PROBE_CHUNK_SIZE = 200
_INTERNAL_PATH = "/api/conversations/internal/verify_org_memberships/"


@dataclass(frozen=True)
class OrgIdentity:
    """A ticket's org attribution plus the identity that must belong to that org.

    ``distinct_id`` and ``email_from`` mirror the fields the enrichment's local
    membership check compares against (a widget's real distinct_id, or the
    provider-supplied email that Slack/Teams/email tickets store).
    """

    organization_id: str
    distinct_id: str
    email_from: str


def cross_region_verification_enabled() -> bool:
    """Only US and EU Cloud split org ownership and share the secret.

    Single-region deployments (dev, self-hosted) have no sibling to probe, and an
    unset secret means the feature isn't provisioned.
    """
    return get_instance_region() in ("US", "EU") and bool(settings.CONVERSATIONS_CROSS_REGION_SECRET)


def _sibling_region_url() -> str:
    # Under DEBUG a single instance stands in for both regions, so loop back through
    # SITE_URL (mirrors the Slack proxy's dev topology).
    if settings.DEBUG:
        return f"{settings.SITE_URL.rstrip('/')}{_INTERNAL_PATH}"
    sibling = "https://eu.posthog.com" if get_instance_region() == "US" else "https://us.posthog.com"
    return f"{sibling}{_INTERNAL_PATH}"


def sign_request(body: bytes, secret: str, *, timestamp: int | None = None) -> tuple[str, str]:
    """HMAC-SHA256 hexdigest over ``v0:{ts}:{body}`` — the sending half of
    ``CrossRegionOrgVerificationAuthentication``. Returns ``(signature, timestamp)``."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    hmac_input = f"v0:{ts}:{body.decode('utf-8')}"
    digest = hmac.new(secret.encode("utf-8"), hmac_input.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()
    return digest, ts


def verify_org_memberships(identities: list[OrgIdentity]) -> set[OrgIdentity]:
    """Return the identities THIS region can confirm via ``OrganizationMembership``.

    An identity verifies when its org has a membership whose user matches the
    ticket identity — by the app user's distinct_id, or by an email equal to the
    ticket's distinct_id or ``email_from``. This mirrors the membership predicate
    in ``conversations_signals._tickets_with_verified_org`` so the local pass and
    the cross-region receiver apply exactly the same rule.
    """
    if not identities:
        return set()

    org_ids = {identity.organization_id for identity in identities}
    memberships = OrganizationMembership.objects.filter(organization_id__in=org_ids).values_list(
        "organization_id", "user__distinct_id", "user__email"
    )

    org_distinct_ids: set[tuple[str, str]] = set()
    org_emails: set[tuple[str, str]] = set()
    for organization_id, distinct_id, email in memberships:
        org = str(organization_id)
        if distinct_id:
            org_distinct_ids.add((org, distinct_id))
        if email:
            org_emails.add((org, email.lower()))

    verified: set[OrgIdentity] = set()
    for identity in identities:
        org = identity.organization_id
        distinct_id = identity.distinct_id
        email_from = identity.email_from
        if (
            (distinct_id and (org, distinct_id) in org_distinct_ids)
            or (distinct_id and (org, distinct_id.lower()) in org_emails)
            or (email_from and (org, email_from.lower()) in org_emails)
        ):
            verified.add(identity)
    return verified


def verify_org_memberships_cross_region(identities: list[OrgIdentity]) -> set[OrgIdentity]:
    """Ask the sibling region which identities it can verify locally.

    Returns the confirmed subset, or an empty set on any failure (feature disabled,
    transport error, non-200, malformed body). A probe failure just means the org
    isn't enriched this run; the daily schedule retries.
    """
    if not identities or not cross_region_verification_enabled():
        return set()

    secret = settings.CONVERSATIONS_CROSS_REGION_SECRET
    url = _sibling_region_url()
    verified: set[OrgIdentity] = set()

    for start in range(0, len(identities), CROSS_REGION_PROBE_CHUNK_SIZE):
        chunk = identities[start : start + CROSS_REGION_PROBE_CHUNK_SIZE]
        body = json.dumps({"identities": [asdict(identity) for identity in chunk]}).encode("utf-8")
        signature, ts = sign_request(body, secret)
        try:
            response = requests.post(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    CROSS_REGION_SIGNATURE_HEADER: signature,
                    CROSS_REGION_TIMESTAMP_HEADER: ts,
                },
                timeout=CROSS_REGION_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            logger.warning("conversations_cross_region_verify_failed", url=url, error=str(e))
            continue

        if response.status_code != 200:
            logger.warning("conversations_cross_region_verify_non_200", url=url, status_code=response.status_code)
            continue

        try:
            data = response.json()
        except ValueError:
            logger.warning("conversations_cross_region_verify_bad_json", url=url)
            continue

        verified_indices = data.get("verified_indices")
        if not isinstance(verified_indices, list):
            logger.warning("conversations_cross_region_verify_bad_payload", url=url)
            continue

        for index in verified_indices:
            if isinstance(index, int) and 0 <= index < len(chunk):
                verified.add(chunk[index])

    return verified

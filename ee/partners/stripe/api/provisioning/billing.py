"""Billing activation via Stripe Shared Payment Tokens (SPT).

Stripe hands the provider a shared payment token in ``payment_credentials``;
activating it against the billing service starts a paid subscription for the
provisioned organization.
"""

from __future__ import annotations

from typing import Any

import requests
import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User

from ee.settings import BILLING_SERVICE_URL

logger = structlog.get_logger(__name__)


def _build_billing_token(team: Team, user: User) -> str | None:
    from posthog.cloud_utils import get_cached_instance_license

    from ee.billing.billing_manager import build_billing_token

    license = get_cached_instance_license()
    if not license:
        return None
    return build_billing_token(license, team.organization, user)


def _team_has_active_billing(team: Team, user: User) -> bool:
    """Check if the team's organization already has an active billing subscription."""
    try:
        billing_token = _build_billing_token(team, user)
        if not billing_token:
            return False

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers={"Authorization": f"Bearer {billing_token}"},
            timeout=30,
        )

        if res.status_code != 200:
            return False

        customer = res.json().get("customer", {})
        return bool(customer.get("has_active_subscription"))
    except Exception:
        capture_exception(additional_properties={"team_id": team.id, "org_id": str(team.organization_id)})
        return False


def _activate_billing_with_spt(team: Team, user: User, spt_token: str) -> bool:
    """Call the billing service to activate a subscription with a Stripe Shared Payment Token.

    Returns True if activation succeeded, False otherwise.
    """
    try:
        billing_token = _build_billing_token(team, user)
        if not billing_token:
            capture_exception(Exception("No license found for SPT billing activation"))
            return False

        res = requests.post(
            f"{BILLING_SERVICE_URL}/api/activate/authorize",
            headers={"Authorization": f"Bearer {billing_token}"},
            json={"shared_payment_token": spt_token},
            timeout=30,
        )

        if res.status_code not in (200, 201):
            capture_exception(
                Exception(f"Billing SPT activation failed: {res.status_code}"),
                {"team_id": team.id, "org_id": str(team.organization_id), "status": res.status_code},
            )
            return False

        logger.info("stripe_provisioning.spt_billing_activated", team_id=team.id, org_id=str(team.organization_id))
        return True
    except Exception:
        capture_exception(additional_properties={"team_id": team.id, "org_id": str(team.organization_id)})
        return False


def extract_spt(payment_credentials: Any) -> str | None:
    if isinstance(payment_credentials, dict) and payment_credentials.get("type") == "stripe_payment_token":
        return payment_credentials.get("stripe_payment_token") or None
    return None


def try_activate_billing_with_spt(payment_credentials: Any, team: Team, user: User) -> bool | None:
    """Activate billing if an SPT is present, skipping if billing is already active.

    Returns True if succeeded or already active, False if failed, None if no SPT was present.
    """
    spt_token = extract_spt(payment_credentials)
    if not spt_token:
        return None
    if _team_has_active_billing(team, user):
        return True
    return _activate_billing_with_spt(team, user, spt_token)

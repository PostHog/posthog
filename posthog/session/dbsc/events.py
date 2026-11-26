from typing import Literal

from django.http import HttpRequest

import structlog
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity
from posthog.session.dbsc.decisions import Action
from posthog.session.dbsc.rollout import Mode
from posthog.utils import get_ip_address, get_short_user_agent

logger = structlog.get_logger(__name__)

REFUSED_ACTIVITY = "session_refused_unbound"

RefusalReason = Literal["missing", "expired", "bad_signature", "wrong_session", "invalid_proof"]

REGISTRATIONS_COUNTER = Counter(
    "posthog_dbsc_registrations_total",
    "DBSC registration attempts, by outcome",
    labelnames=["outcome"],
)
REFRESHES_COUNTER = Counter(
    "posthog_dbsc_refreshes_total",
    "DBSC bound-cookie refresh attempts, by outcome",
    labelnames=["outcome"],
)
# skipped="true" marks browsers that could not refresh, and cross_site="true" requests that another site started.
REFUSALS_COUNTER = Counter(
    "posthog_dbsc_refusals_total",
    "Bound sessions that arrived without a valid bound cookie, by mode, reason and action",
    labelnames=["mode", "reason", "action", "skipped", "cross_site"],
)


# The activity log encoder writes a context out through __dict__, which slots would remove.
@frozen(slots=False)
class SessionRefusedContext(ActivityContextBase):
    reason: RefusalReason
    ip_address: str
    user_agent: str


def record_registration(outcome: str, *, user_id: int | None) -> None:
    REGISTRATIONS_COUNTER.labels(outcome=outcome).inc()
    if outcome == "bound":
        logger.info("dbsc_registered", user_id=user_id)
    else:
        logger.info("dbsc_registration_failed", outcome=outcome, user_id=user_id)


def record_refresh(outcome: str, *, user_id: int | None) -> None:
    REFRESHES_COUNTER.labels(outcome=outcome).inc()
    if outcome not in ("refreshed", "challenged"):
        logger.info("dbsc_refresh_failed", outcome=outcome, user_id=user_id)


def record_refusal(
    request: HttpRequest,
    user: User,
    *,
    mode: Mode,
    reason: RefusalReason,
    action: Action,
    skipped: bool,
    cross_site: bool,
    impersonated: bool,
) -> None:
    REFUSALS_COUNTER.labels(
        mode=mode.value,
        reason=reason,
        action=action.value,
        skipped=str(skipped).lower(),
        cross_site=str(cross_site).lower(),
    ).inc()
    logger.warning(
        "dbsc_refused",
        mode=mode.value,
        reason=reason,
        action=action.value,
        skipped=skipped,
        cross_site=cross_site,
        impersonated=impersonated,
        user_id=user.id,
        path=request.path,
    )
    # An impersonated session carries the staff member's binding, which never belongs in the customer's log.
    if action != Action.END_SESSION or impersonated or user.current_organization_id is None:
        return
    log_activity(
        organization_id=user.current_organization_id,
        team_id=None,
        user=user,
        item_id=str(user.id),
        scope="User",
        activity=REFUSED_ACTIVITY,
        detail=Detail(
            name=user.email,
            context=SessionRefusedContext(
                reason=reason,
                ip_address=get_ip_address(request),
                user_agent=get_short_user_agent(request),
            ),
        ),
        was_impersonated=False,
    )

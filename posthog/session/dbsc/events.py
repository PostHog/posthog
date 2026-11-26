import dataclasses

from django.http import HttpRequest

import structlog
from prometheus_client import Counter

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity
from posthog.session.dbsc.rollout import Mode
from posthog.utils import get_ip_address, get_short_user_agent

logger = structlog.get_logger(__name__)

REFUSED_ACTIVITY = "session_refused_unbound"

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
# skipped="true" marks browsers that could not refresh. The rest carried the session cookie alone.
REFUSALS_COUNTER = Counter(
    "posthog_dbsc_refusals_total",
    "Bound sessions that arrived without a valid bound cookie, by mode and reason",
    labelnames=["mode", "reason", "skipped"],
)


@dataclasses.dataclass(frozen=True)
class SessionRefusedContext(ActivityContextBase):
    reason: str
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
    request: HttpRequest, user: User, *, mode: Mode, reason: str, skipped: bool, impersonated: bool
) -> None:
    REFUSALS_COUNTER.labels(mode=mode.value, reason=reason, skipped=str(skipped).lower()).inc()
    logger.warning(
        "dbsc_refused",
        mode=mode.value,
        reason=reason,
        skipped=skipped,
        impersonated=impersonated,
        user_id=user.id,
        path=request.path,
    )
    # An impersonated session carries the staff member's binding, which never belongs in the customer's log.
    if mode != Mode.ENFORCE or impersonated or user.current_organization_id is None:
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

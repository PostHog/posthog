"""Tells a person when a destination refuses an alert's message, because every later message fails the same way.

The alert's creator gets an in-app notification and an email. When the creator cannot get the
in-app notification, because they left, lost access to the project, turned that notification type
off, or the alert records no creator, the project's members get it instead. A source registers how
to find an alert's creator when Django starts, because the platform imports no source.

Everyone told must be allowed to view the alert's source, so a notice names no alert to a member
that source's access rules hide it from.

One destination is noticed at most once per UTC day. Every check that fires sends again, and an
insight alert sends on every check while it fires, so a notice per send would repeat all day. A
daily marker, written once every channel has sent, skips the repeats before any query runs. A
short claim stops concurrent sends from noticing together, and the notification and email keys
stop a duplicate when a channel is retried.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Final, cast
from urllib.parse import urlsplit

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen
from posthog.email import EmailMessage, is_email_available
from posthog.models import Team, User
from posthog.slack.channels import clip_text

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DestinationRefused
from products.alerts_platform.backend.delivery.wire import credential_digest
from products.alerts_platform.backend.facade.contracts import SourceAlertCreator, SourceKind
from products.alerts_platform.backend.models import PlatformAlertConfiguration
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationResourceType,
    NotificationType,
    Priority,
    RecipientsResolver,
    TargetType,
    create_notification,
)

EMAIL_TEMPLATE_NAME = "alert_destination_refused"
MAX_TITLE_CHARS = 100
# Longer than the day the key names, so the marker outlives every send that builds it.
_NOTICED_TTL_SECONDS = 2 * 24 * 60 * 60
# Longer than one notice takes, and short enough that a worker that dies holding it delays the
# notice by minutes, not by the rest of the day.
_CLAIM_TTL_SECONDS = 5 * 60

# The access-control resource that governs each source's alerts. A source missing here is checked
# for project access only.
_ACCESS_RESOURCES: Final[dict[SourceKind, NotificationResourceType]] = {
    SourceKind.LOGS: "logs",
    SourceKind.INSIGHT: "insight",
    SourceKind.METRICS: "metrics",
}

logger = structlog.get_logger(__name__)

_creators: dict[SourceKind, SourceAlertCreator] = {}


def register_creator(source: SourceKind, lookup: SourceAlertCreator) -> None:
    registered = _creators.get(source)
    if registered is not None and registered is not lookup:
        raise RuntimeError(f"A different creator lookup is already registered for {source} alerts.")
    _creators[source] = lookup


@frozen
class RefusalNotice:
    """What a notice says, in plain values, because it crosses into a Celery task."""

    team_id: int
    key: str
    configuration_id: str
    source: str
    alert_name: str
    alert_url: str
    refusal: str


def notify_refused(
    *,
    team_id: int,
    message: AlertMessage,
    destination: str,
    refusal: DestinationRefused,
    now: datetime | None = None,
) -> None:
    """Queues a notice of one refused send. `destination` is where the send went, and changes when it is repointed.

    A repointed destination is a new destination, so a URL fixed and broken again on the same day
    is noticed again. The notice is sent from a task, because checking a large project's members
    against access rules can outlast the delivery activity. Never raises, because the send's own
    error is the one the caller reports.
    """
    from products.alerts_platform.backend.tasks.refusal_notices import send_refusal_notice  # noqa: PLC0415

    day = (now or datetime.now(UTC)).date().isoformat()
    key = "alert-destination-refused:" + credential_digest(f"{team_id}|{message.configuration_id}|{destination}|{day}")
    notice = RefusalNotice(
        team_id=team_id,
        key=key,
        configuration_id=message.configuration_id,
        source=message.source.value,
        alert_name=message.alert_name,
        alert_url=message.alert_url,
        refusal=str(refusal),
    )
    try:
        if cache.get(key) or not cache.add(_claim(key), True, timeout=_CLAIM_TTL_SECONDS):
            return
        try:
            send_refusal_notice.delay(**asdict(notice))
        except Exception:
            cache.delete(_claim(key))
            raise
    except Exception:
        logger.exception("alert_destination_refused_notice_failed", team_id=team_id, alert_id=message.configuration_id)


def send_notice(notice: RefusalNotice) -> None:
    """Sends a queued notice, and marks the day noticed once every channel has sent."""
    try:
        if _notify_everyone(notice):
            cache.set(notice.key, True, timeout=_NOTICED_TTL_SECONDS)
    finally:
        cache.delete(_claim(notice.key))


def _claim(key: str) -> str:
    return f"{key}:claim"


def _notify_everyone(notice: RefusalNotice) -> bool:
    """Sends on every channel, each apart from the others. Returns whether all of them sent."""
    team_id, key = notice.team_id, notice.key
    title = clip_text(f"An alert destination refused a notification from {notice.alert_name}", MAX_TITLE_CHARS)
    body = f"{notice.refusal} Every notification sent there will fail until the destination is fixed."
    url = urlsplit(notice.alert_url)
    # The query too: an insight alert's link selects the alert with `?alert_id=`.
    source_url = f"{url.path}?{url.query}" if url.query else url.path
    resource_type = _ACCESS_RESOURCES.get(SourceKind(notice.source))

    creator = _reachable_creator(notice, resource_type)
    sent = True
    try:
        notified = creator is not None and _notify(
            notice, TargetType.USER, str(creator.id), key, title, body, source_url, resource_type
        )
        if not notified:
            _notify(notice, TargetType.TEAM, str(team_id), f"{key}:team", title, body, source_url, resource_type)
    except Exception:
        sent = False
        logger.exception("alert_destination_refused_in_app_failed", team_id=team_id, alert_id=notice.configuration_id)
    if creator is not None:
        try:
            _email(creator, notice)
        except Exception:
            sent = False
            logger.exception(
                "alert_destination_refused_email_failed", team_id=team_id, alert_id=notice.configuration_id
            )
    return sent


def _reachable_creator(notice: RefusalNotice, resource_type: NotificationResourceType | None) -> User | None:
    lookup = _creators.get(SourceKind(notice.source))
    if lookup is None:
        return None
    configuration = (
        PlatformAlertConfiguration.objects.for_team(notice.team_id)
        .filter(id=notice.configuration_id)
        .only("id", "legacy_configuration_id")
        .first()
    )
    if configuration is None:
        return None
    creator_id = lookup(team_id=notice.team_id, alert_id=configuration.destination_alert_id)
    if creator_id is None:
        return None
    team = Team.objects.get(id=notice.team_id)
    creator = team.all_users_with_access().filter(id=creator_id, is_active=True).first()
    if creator is None or resource_type is None:
        return creator
    allowed = RecipientsResolver().filter_by_access_control([creator.id], cast(str, resource_type), team)
    return creator if allowed else None


def _notify(
    notice: RefusalNotice,
    target_type: TargetType,
    target_id: str,
    key: str,
    title: str,
    body: str,
    source_url: str,
    resource_type: NotificationResourceType | None,
) -> bool:
    event = create_notification(
        NotificationData(
            team_id=notice.team_id,
            notification_type=NotificationType.ALERT_DESTINATION_REFUSED,
            priority=Priority.NORMAL,
            title=title,
            body=body,
            target_type=target_type,
            target_id=target_id,
            source_url=source_url,
            # An access-controlled resource type makes the notification skip anyone denied it.
            resource_type=resource_type,
            # The inbox groups notifications by resource, so each alert keeps its own group.
            resource_id=notice.configuration_id,
            idempotency_key=key,
        )
    )
    return event is not None


def _email(creator: User, notice: RefusalNotice) -> None:
    if not is_email_available(with_absolute_urls=True):
        return
    email = EmailMessage(
        campaign_key=notice.key,
        template_name=EMAIL_TEMPLATE_NAME,
        subject=f"An alert destination refused a notification from {' '.join(notice.alert_name.split())}",
        template_context={
            "alert_name": notice.alert_name,
            "alert_url": notice.alert_url,
            "refusal": notice.refusal,
        },
    )
    email.add_user_recipient(creator)
    email.send()

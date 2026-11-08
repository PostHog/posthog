"""Tells a person when a destination refuses an alert's message, because every later message fails the same way.

The alert's creator gets an in-app notification and an email. When the creator cannot get the
in-app notification, because they left, lost access to the project, turned that notification type
off, or the alert records no creator, the project's members get it instead. A source registers how
to find an alert's creator when Django starts, because the platform imports no source.

One destination is noticed at most once per UTC day. Every check that fires sends again, and an
insight alert sends on every check while it fires, so a notice per send would repeat all day.
"""

from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured

import structlog

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
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)

EMAIL_TEMPLATE_NAME = "alert_destination_refused"
MAX_TITLE_CHARS = 100

logger = structlog.get_logger(__name__)

_creators: dict[SourceKind, SourceAlertCreator] = {}


def register_creator(source: SourceKind, lookup: SourceAlertCreator) -> None:
    registered = _creators.get(source)
    if registered is not None and registered is not lookup:
        raise RuntimeError(f"A different creator lookup is already registered for {source} alerts.")
    _creators[source] = lookup


def notify_refused(
    *,
    team_id: int,
    message: AlertMessage,
    destination: str,
    refusal: DestinationRefused,
    now: datetime | None = None,
) -> None:
    """Notices one refused send. `destination` names the destination and changes when it is repointed.

    A repointed destination is a new destination, so a URL fixed and broken again on the same day
    is noticed again.
    """
    day = (now or datetime.now(UTC)).date().isoformat()
    key = "alert-destination-refused:" + credential_digest(f"{team_id}|{message.configuration_id}|{destination}|{day}")
    title = clip_text(f"An alert destination refused a notification from {message.alert_name}", MAX_TITLE_CHARS)
    body = f"{refusal} Every notification sent there will fail until the destination is fixed."
    source_url = urlsplit(message.alert_url).path

    creator = _reachable_creator(team_id, message)
    notified = creator is not None and _notify(team_id, TargetType.USER, str(creator.id), key, title, body, source_url)
    if not notified:
        _notify(team_id, TargetType.TEAM, str(team_id), f"{key}:team", title, body, source_url)
    if creator is not None:
        _email(creator, key, message, refusal)


def _reachable_creator(team_id: int, message: AlertMessage) -> User | None:
    lookup = _creators.get(message.source)
    if lookup is None:
        return None
    configuration = (
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(id=message.configuration_id)
        .only("id", "legacy_configuration_id")
        .first()
    )
    if configuration is None:
        return None
    creator_id = lookup(team_id=team_id, alert_id=UUID(str(configuration.destination_alert_id)))
    if creator_id is None:
        return None
    team = Team.objects.get(id=team_id)
    return team.all_users_with_access().filter(id=creator_id, is_active=True).first()


def _notify(
    team_id: int, target_type: TargetType, target_id: str, key: str, title: str, body: str, source_url: str
) -> bool:
    event = create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.ALERT_DESTINATION_REFUSED,
            priority=Priority.NORMAL,
            title=title,
            body=body,
            target_type=target_type,
            target_id=target_id,
            source_url=source_url,
            idempotency_key=key,
        )
    )
    return event is not None


def _email(creator: User, key: str, message: AlertMessage, refusal: DestinationRefused) -> None:
    if not is_email_available(with_absolute_urls=True):
        return
    try:
        email = EmailMessage(
            campaign_key=key,
            template_name=EMAIL_TEMPLATE_NAME,
            subject=f"An alert destination refused a notification from {' '.join(message.alert_name.split())}",
            template_context={
                "alert_name": message.alert_name,
                "alert_url": message.alert_url,
                "refusal": str(refusal),
            },
        )
    except ImproperlyConfigured:
        logger.warning("alert_destination_refused_email_unavailable", alert_id=message.configuration_id)
        return
    email.add_user_recipient(creator)
    email.send()

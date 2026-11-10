"""Tells an alert's creator when a destination refuses the alert's message, because every later message fails the same way.

The creator gets an in-app notification and an email while they can still access the project and
see the alert, by the access rules of the source that owns it. A creator who lost access to an
insight would otherwise learn the alert's name and status after losing it. An alert
whose source records no creator is noticed by nobody. A source registers how to find an alert's
creator when Django starts, because the platform imports no source. The email follows the creator's
"Data pipeline errors" email setting, as other destination failure emails do.

One destination is noticed at most once per UTC day. Every check that fires sends again, and an
insight alert sends on every check while it fires, so a notice per send would repeat all day. The
notification and email keys name the day, so a repeat sends nothing. A cache marker, written once
both channels have sent, skips the queries for a repeat.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from django.core.cache import cache

import structlog

from posthog.email import EmailMessage, is_email_available
from posthog.models import Team, User
from posthog.models.organization_notification_lock import notification_locks_for_users
from posthog.slack.channels import clip_text

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DestinationRefused
from products.alerts_platform.backend.delivery.wire import credential_digest
from products.alerts_platform.backend.facade.contracts import SourceAlertCreator, SourceKind
from products.alerts_platform.backend.logic import source_access
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
# Longer than the day the key names, so the marker outlives every send that builds it.
_NOTICED_TTL_SECONDS = 2 * 24 * 60 * 60

logger = structlog.get_logger(__name__)

_creators: dict[SourceKind, SourceAlertCreator] = {}

_Channel = Callable[[int, User, str, AlertMessage, DestinationRefused], None]


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
    """Notices one refused send. `destination` is where the send went, and changes when it is repointed.

    A repointed destination is a new destination, so a URL fixed and broken again on the same day
    is noticed again. Never raises, because the send's own error is the one the caller reports.
    """
    day = (now or datetime.now(UTC)).date().isoformat()
    key = "alert-destination-refused:" + credential_digest(f"{team_id}|{message.configuration_id}|{destination}|{day}")
    try:
        if cache.get(key):
            return
        creator = _creator(team_id, message)
        if creator is None:
            return
        # Each channel apart, so one failing still sends the other. A failed channel leaves the
        # marker unset, and the next refusal tries both again under the same keys.
        sent = _try(_notify, team_id, creator, key, message, refusal)
        sent = _try(_email, team_id, creator, key, message, refusal) and sent
        if sent:
            cache.set(key, True, timeout=_NOTICED_TTL_SECONDS)
    except Exception:
        logger.exception("alert_destination_refused_notice_failed", team_id=team_id, alert_id=message.configuration_id)


def _creator(team_id: int, message: AlertMessage) -> User | None:
    """The alert's creator, if they can still access the project and see the alert."""
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
    alert_id = configuration.destination_alert_id
    creator_id = lookup(team_id=team_id, alert_id=alert_id)
    if creator_id is None:
        return None
    creator = Team.objects.get(id=team_id).all_users_with_access().filter(id=creator_id, is_active=True).first()
    if creator is not None and source_access.can_view(
        message.source, team_id=team_id, alert_id=alert_id, user_id=creator.id
    ):
        return creator
    return None


def _try(
    channel: _Channel, team_id: int, creator: User, key: str, message: AlertMessage, refusal: DestinationRefused
) -> bool:
    try:
        channel(team_id, creator, key, message, refusal)
    except Exception:
        logger.exception(
            "alert_destination_refused_channel_failed",
            channel=channel.__name__,
            team_id=team_id,
            alert_id=message.configuration_id,
        )
        return False
    return True


def _notify(team_id: int, creator: User, key: str, message: AlertMessage, refusal: DestinationRefused) -> None:
    url = urlsplit(message.alert_url)
    create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.ALERT_DESTINATION_REFUSED,
            priority=Priority.NORMAL,
            title=clip_text(f"An alert destination refused a notification from {message.alert_name}", MAX_TITLE_CHARS),
            body=f"{refusal} Every notification sent there will fail until the destination is fixed.",
            target_type=TargetType.USER,
            target_id=str(creator.id),
            # The query too: an insight alert's link selects the alert with `?alert_id=`.
            source_url=f"{url.path}?{url.query}" if url.query else url.path,
            # The inbox groups notifications by resource, so each alert keeps its own group.
            resource_id=message.configuration_id,
            idempotency_key=key,
        )
    )


def _email(team_id: int, creator: User, key: str, message: AlertMessage, refusal: DestinationRefused) -> None:
    if not is_email_available(with_absolute_urls=True):
        return
    if not _wants_pipeline_error_emails(team_id, creator):
        return
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
    email.add_user_recipient(creator)
    email.send()


def _wants_pipeline_error_emails(team_id: int, creator: User) -> bool:
    # posthog.tasks.email imports the query and LLM stacks, and this module loads during django.setup().
    from posthog.tasks.email import should_send_notification, should_send_pipeline_error_notification  # noqa: PLC0415

    organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).get()
    # Only this organization's rules apply, so an admin elsewhere cannot silence this email.
    locks = notification_locks_for_users([creator.id], organization_id=organization_id).get(creator.id, {})
    return should_send_notification(
        creator, "plugin_disabled", locks=locks
    ) and should_send_pipeline_error_notification(creator, team_id=team_id, locks=locks)

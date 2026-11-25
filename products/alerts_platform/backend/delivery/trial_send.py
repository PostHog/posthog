"""A test message to the destinations the platform sends an alert's firings to.

It is sent once and threads nothing, so it skips the thread store, and it records nothing in the
destinations' delivery health, which a failed test would otherwise mark as broken.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from celery.exceptions import SoftTimeLimitExceeded

from posthog.models import Team
from posthog.utils import absolute_uri

from products.alerts_platform.backend.delivery import evaluation, legacy_webhook
from products.alerts_platform.backend.delivery.message import AlertMessage, build_delivery_test_message
from products.alerts_platform.backend.delivery.transport import DeliveryTransport
from products.alerts_platform.backend.delivery.webhook import WebhookTransport
from products.alerts_platform.backend.facade.contracts import (
    DeliveryTestOutcome,
    MessageLink,
    SourceKind,
    StoredAlertDestination,
)
from products.alerts_platform.backend.logic.alert_destinations import delivery_test_destinations

logger = structlog.get_logger(__name__)


def send_delivery_test(
    *, team_id: int, public_id: UUID, source: SourceKind, alert_name: str, source_alert_url: str
) -> DeliveryTestOutcome:
    destinations = delivery_test_destinations(team_id=team_id, public_id=public_id)
    if not destinations:
        return DeliveryTestOutcome(sent=0, failed=0)
    team = Team.objects.get(id=team_id)
    message = build_delivery_test_message(
        source=source,
        configuration_id=str(destinations[0].configuration_id),
        alert_name=alert_name,
        alert_url=source_alert_url,
        occurred_at=datetime.now(UTC),
        project=MessageLink(label=team.name, url=absolute_uri(f"/project/{team.id}")),
    )
    sent = 0
    failed = 0
    for destination in destinations:
        try:
            transport = _transport(team, source, public_id, destination)
            transport.deliver(team_id=team_id, target=destination.data, message=message)
        # The task's time limit, which has to end the test rather than count as one destination failing.
        except SoftTimeLimitExceeded:
            raise
        except Exception as error:
            # Named by class: an exception's text can carry the destination's credential URL.
            logger.warning(
                "alerts_platform_delivery_test_failed",
                team_id=team_id,
                destination_id=str(destination.id),
                destination_type=destination.data["type"],
                error=type(error).__name__,
            )
            failed += 1
        else:
            sent += 1
    return DeliveryTestOutcome(sent=sent, failed=failed)


def _transport(
    team: Team, source: SourceKind, public_id: UUID, destination: StoredAlertDestination
) -> DeliveryTransport:
    transport_class = evaluation._TRANSPORTS[destination.data["type"]]
    if transport_class is not WebhookTransport:
        return transport_class()
    return WebhookTransport(legacy_body=_legacy_body(team, source, public_id, destination))


def _legacy_body(
    team: Team, source: SourceKind, public_id: UUID, destination: StoredAlertDestination
) -> Callable[[AlertMessage], dict[str, Any]] | None:
    """The body a firing would send this webhook, so the test shows its receiver the same shape."""
    body = legacy_webhook.body_for(source)
    if body is None:
        return None
    if not destination.keeps_legacy_webhook_body:
        keeps = legacy_webhook.keeps_legacy_webhook_body(team)
        if keeps is None:
            raise RuntimeError("Could not read which webhook body this team receives.")
        if not keeps:
            return None
    return lambda message: body(
        project_id=team.id,
        alert_id=str(public_id),
        alert_name=message.alert_name,
        consecutive_failures=0,
        transition=message.transition,
    )

"""Contract types for insight alerts.

Framework-free values this product hands to its consumers. The alerting vocabulary every source
shares lives in `products.alerts_platform.backend.facade.contracts`; what stays here is what only
an insight alert means, and the hooks other sources use to reach this product's destinations.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.schema_enums import AlertState

from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    DeliveryPath,
    DestinationType,
    IncidentAction,
)
from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT

# The internal event an insight alert's destinations fire on. Do not take it from
# `posthog.tasks.alerts.utils` instead, because that module imports this product's facade.
INSIGHT_ALERT_EVENT_IDS: Final[tuple[str, ...]] = (LEGACY_INSIGHT_ALERT_EVENT,)

# Every move into and out of a firing, so each trigger gets its resolve while messages still announce none.
INSIGHT_ALERT_INCIDENT_OPENED_EVENT: Final = "$insight_alert_incident_opened"
INSIGHT_ALERT_INCIDENT_CLOSED_EVENT: Final = "$insight_alert_incident_closed"
INSIGHT_EVENT_IDS_BY_INCIDENT_ACTION: Final[dict[str, str]] = {
    IncidentAction.TRIGGER.value: INSIGHT_ALERT_INCIDENT_OPENED_EVENT,
    IncidentAction.RESOLVE.value: INSIGHT_ALERT_INCIDENT_CLOSED_EVENT,
}
# Every event an insight alert's own destinations can listen on. The generic HogFunction API treats
# the incident events as managed and refuses to edit them, so the insight API must be able to remove them.
INSIGHT_ALERT_DESTINATION_EVENT_IDS: Final[tuple[str, ...]] = (
    *INSIGHT_ALERT_EVENT_IDS,
    *INSIGHT_EVENT_IDS_BY_INCIDENT_ACTION.values(),
)

# Slack only, because `alert:write` is grantable to a sandboxed agent. A connected workspace is a
# destination an admin chose, while every other transport takes a URL the caller supplies.
INSIGHT_ALERT_DESTINATION_TYPES: Final[tuple[DestinationType, ...]] = (DestinationType.SLACK,)


class DestinationHoldBack(StrEnum):
    """Why native delivery cannot send what an alert destination sends today."""

    NO_TEMPLATE = "no_template"
    OTHER_TEMPLATE = "other_template"
    CODE = "code"
    CUSTOM_INPUTS = "custom_inputs"
    FILTERS = "filters"
    MASKING = "masking"
    MAPPINGS = "mappings"
    MESSAGE = "message"
    MESSAGE_COSMETIC = "message_cosmetic"
    WEBHOOK_BODY = "webhook_body"
    WEBHOOK_METHOD = "webhook_method"
    WEBHOOK_TEMPLATED_HEADER = "webhook_templated_header"
    # An added header native delivery cannot send, such as an invalid name or a control character.
    WEBHOOK_HEADERS = "webhook_headers"
    # Native delivery refuses the destination, such as a plain-HTTP webhook URL or an unknown
    # PagerDuty severity, so it would send nothing.
    REFUSED_ADDRESS = "refused_address"
    # Native delivery sends to the stored address as written and does not render a template in it.
    TEMPLATED_ADDRESS = "templated_address"
    # Native delivery does not sign requests, so a receiver that checks the signature rejects them.
    WEBHOOK_SIGNING = "webhook_signing"
    # Saved again after it was built, before edits were recorded, so what changed is unknown.
    UNTRACKED_EDIT = "untracked_edit"


class DestinationBucket(StrEnum):
    """Where an alert destination goes at cutover, from its most restrictive hold-back.

    Listed from the most to the least restrictive. `CODE` covers every edited-code bucket, because
    which one applies depends on what the code does, which this classifier does not read.
    """

    REFUSED_ADDRESS = "R1"
    CODE = "code"
    PORTABLE = "W1"
    COSMETIC = "C1"
    TEMPLATED_HEADERS = "N2"
    STATIC_HEADERS = "N1"
    STOCK = "N0"


class HogFunctionPathReason(StrEnum):
    """Why an alert the platform owns sends through its HogFunctions rather than natively."""

    CUSTOMIZED = "customized"
    # A function takes the source's alert events without being bound to one alert. Native
    # delivery reads destinations per alert, so it would never send to it.
    UNBOUND = "unbound"
    WEBHOOK_BODY_UNKNOWN = "webhook_body_unknown"
    # Native delivery cannot send this source's legacy webhook body, and the team keeps it.
    LEGACY_WEBHOOK_BODY_NOT_NATIVE = "legacy_webhook_body_not_native"
    # Native delivery sends PagerDuty incident actions only, never the firing event.
    PAGERDUTY_NOT_NATIVE = "pagerduty_not_native"


@frozen
class DeliveryPathChoice:
    reason: HogFunctionPathReason | None = None

    @property
    def path(self) -> DeliveryPath:
        return DeliveryPath.NATIVE if self.reason is None else DeliveryPath.HOG_FUNCTION


@frozen
class DestinationEligibility:
    """One alert destination function, and every reason native delivery cannot take it over."""

    hog_function_id: UUID
    template_id: str | None
    hold_backs: tuple[DestinationHoldBack, ...]
    # The md5 of the function's code, so the same code can be recognized across functions and teams.
    code_hash: str
    event_ids: frozenset[str]


@frozen
class BucketedDestination:
    """One alert destination function in a cutover bucket report."""

    team_id: int
    # None for a function bound to no single alert, which fires for several alerts of the team.
    alert_id: str | None
    eligibility: DestinationEligibility


@frozen
class FiringAlert:
    id: UUID
    name: str
    insight_name: str | None
    insight_short_id: str


@frozen
class EnabledAlert:
    id: UUID
    name: str
    insight_name: str | None
    insight_short_id: str


@frozen
class ErroredAlert:
    id: UUID
    name: str
    insight_name: str | None
    insight_short_id: str
    # None for an alert the platform owns, whose checks it keeps in ClickHouse.
    last_checked_at: datetime | None


@frozen
class AlertInternalEvent:
    """One internal event that makes an alert's HogFunction destinations fire."""

    event_name: str
    properties: dict[str, Any]
    timestamp: datetime
    # Stable across attempts, so a receiver can drop an event a retry emits again.
    uuid: str


class AlertInternalEventsNotDelivered(Exception):
    """The broker did not take every event, so the caller retries."""


@frozen
class MovedAlertRuntime:
    """Where an alert the platform owns stands, in the insight alert's terms."""

    state: AlertState
    next_check_at: datetime | None
    last_notified_at: datetime | None


@frozen
class MovedAlertLastCheck:
    checked_at: datetime
    value: float | None


@frozen
class MovedAlertStatus:
    """What the insight alert API shows for an alert the platform owns, in place of its own row."""

    # None when the platform holds no runtime for the alert.
    runtime: MovedAlertRuntime | None
    # None when the alert has no recent check, or the platform's history could not be read.
    last_check: MovedAlertLastCheck | None


@frozen
class MovedAlertCheck:
    """One check of an alert the platform owns, in the insight alert's terms."""

    # The same on every read, so a client can key on it.
    id: UUID
    checked_at: datetime
    value: float | None
    state: AlertState
    error_message: str | None
    # Names a failed check's reason, for the reasons the history shows by their code.
    error_code: str | None = None
    # A detector check's own output, as production keeps it on its check. Empty for a threshold check.
    anomaly_scores: tuple[float | None, ...] = ()
    triggered_points: tuple[int, ...] = ()
    triggered_dates: tuple[str, ...] = ()
    interval: str | None = None
    triggered_metadata: dict[str, Any] | None = None
    investigation_status: str | None = None
    investigation_verdict: str | None = None
    investigation_summary: str | None = None
    investigation_notebook_short_id: str | None = None
    notification_suppressed_by_agent: bool = False


@frozen
class MovedAlertCheckPage:
    # How many checks the requested window holds, past this page too.
    total: int
    checks: tuple[MovedAlertCheck, ...]


class MovedAlertHistoryUnavailable(Exception):
    """The platform's check history of an alert it owns could not be read."""


@frozen
class MovedAlertSettings:
    """A moved alert's settings as its platform copy holds them."""

    # By the insight row field each one replaces.
    fields: Mapping[str, Any]
    threshold: dict[str, Any] | None
    schedule_start_time: str | None


class PlatformCannotOwn(ValueError):
    """An edit that would leave an alert the platform owns in a shape the platform cannot evaluate."""


@frozen
class InvestigationRelease:
    """What a finished investigation of a platform evaluation hands back to the agent's workflow."""

    # What the workflow starts: the held firing when the verdict let it go out, or the
    # announcement of a changed verdict on a firing that already went out.
    deliveries: tuple[AlertDeliveryRequest, ...]
    previous_verdict: str | None

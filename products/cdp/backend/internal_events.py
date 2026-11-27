import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Optional, Protocol

import structlog
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.kafka_client.client import ProduceResult
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_CDP_INTERNAL_EVENTS

logger = structlog.get_logger(__name__)

# Single source of truth for the managed-alert event boundary. Also used as a Postgres regex
# filter (products/cdp hog_function queryset) and mirrored in the Node CDP consumer, so keep it
# POSIX-compatible (no (?:...) groups).
MANAGED_ALERT_EVENT_PATTERN = (
    r"^\$[a-z0-9_]+_alert_(firing|resolved|errored|auto_disabled|broken|match|incident_opened|incident_closed)$"
)
LEGACY_INSIGHT_ALERT_EVENT = "$insight_alert_firing"
_MANAGED_ALERT_EVENT = re.compile(MANAGED_ALERT_EVENT_PATTERN)


WORKFLOW_STEP_RESUME_EVENT = "$workflow_step_resume"

# Internal events that only the product which emits them may consume. A user-created
# destination cannot subscribe to one, because its properties carry that product's data and
# forwarding them off-platform would bypass the read permission the product enforces on it.
RESERVED_INTERNAL_EVENTS = frozenset({WORKFLOW_STEP_RESUME_EVENT})


def is_reserved_internal_event(event_name: object) -> bool:
    """Return whether an internal event is closed to user-created destinations."""
    return isinstance(event_name, str) and event_name in RESERVED_INTERNAL_EVENTS


# Internal events that carry a product's data, keyed to the scope object that guards reading it. A destination
# on one can send that data out of PostHog, so working with it needs the same read access. The keys are mirrored
# in nodejs/src/cdp/read-guarded-internal-events.ts, which keeps their log text out of shared stores.
INTERNAL_EVENT_READ_SCOPES: dict[str, str] = {
    "$signals_report_ready": "inbox",
}


def internal_event_read_scope(event_name: object) -> str | None:
    """Return the scope object whose read access a destination on this internal event needs."""
    return INTERNAL_EVENT_READ_SCOPES.get(event_name) if isinstance(event_name, str) else None


def is_managed_alert_internal_event(event_name: object) -> bool:
    """Return whether an internal event is reserved for an alert-owned destination."""
    return (
        isinstance(event_name, str)
        and event_name != LEGACY_INSIGHT_ALERT_EVENT
        and _MANAGED_ALERT_EVENT.fullmatch(event_name) is not None
    )


# Alert products whose destinations stay editable through the generic hog functions API, keyed by
# the prefix of their alert events and valued by the API scope objects their own alert API checks.
# An edit through the generic API requires each of those write scopes and editor access on each,
# on top of the hog function ones, so a token or member that cannot touch the alert cannot touch its
# destination either. Metrics and traces alerts are served by the platform alerts API, which also
# checks `alert`. Insight alerts are gated per insight, not by a resource-wide level, so they also
# need the edit gate below. The other alert products stay read-only there.
_INSIGHT_ALERT_EVENT_PREFIX = "$insight_alert_"
GENERIC_API_EDITABLE_ALERT_EVENT_SCOPES: dict[str, tuple[str, ...]] = {
    "$logs_alert_": ("logs",),
    "$metrics_alert_": ("metrics", "alert"),
    "$traces_alert_": ("tracing", "alert"),
    _INSIGHT_ALERT_EVENT_PREFIX: ("alert",),
}


class AlertDestinationEditGate(Protocol):
    def __call__(
        self,
        *,
        team_id: int,
        alert_ids: Collection[str],
        user_id: int,
        key_scopes: Collection[str] | None,
    ) -> str | None: ...


# The per-alert checks an alert product's own API applies, which the generic API must apply too. The
# products register them from their app config, because cdp cannot import them. A prefix listed here
# with no registered gate refuses every edit, so a missing registration cannot open the destinations.
_GATED_ALERT_EVENT_PREFIXES: frozenset[str] = frozenset({_INSIGHT_ALERT_EVENT_PREFIX})
_alert_destination_edit_gates: dict[str, AlertDestinationEditGate] = {}


def register_alert_destination_edit_gate(event_prefix: str, gate: AlertDestinationEditGate) -> None:
    _alert_destination_edit_gates[event_prefix] = gate


def _refuse_ungated_edit(**_: Any) -> str:
    return "This alert destination can only be edited from its alert."


def alert_destination_edit_gate(event_name: object) -> AlertDestinationEditGate | None:
    """The per-alert check a generic-API edit of this alert event's destinations must pass, if any."""
    if not is_managed_alert_internal_event(event_name):
        return None
    prefix = next((prefix for prefix in _GATED_ALERT_EVENT_PREFIXES if str(event_name).startswith(prefix)), None)
    if prefix is None:
        return None
    return _alert_destination_edit_gates.get(prefix, _refuse_ungated_edit)


def generic_api_editable_alert_scopes(event_name: object) -> tuple[str, ...]:
    """Return the scope objects that guard generic-API edits of a managed alert event's destinations,
    or nothing when the generic API cannot edit them."""
    if not is_managed_alert_internal_event(event_name):
        return ()
    return next(
        (
            scopes
            for prefix, scopes in GENERIC_API_EDITABLE_ALERT_EVENT_SCOPES.items()
            if str(event_name).startswith(prefix)
        ),
        (),
    )


@dataclass
class InternalEventEvent:
    event: str
    distinct_id: str
    properties: dict
    timestamp: Optional[str] = None
    url: Optional[str] = None
    uuid: Optional[str] = None


@dataclass
class InternalEventPerson:
    id: str
    properties: dict
    name: Optional[str] = None
    url: Optional[str] = None


@dataclass
class InternalEvent:
    team_id: int
    event: InternalEventEvent
    person: Optional[InternalEventPerson] = None


class InternalEventSerializer(DataclassSerializer):
    class Meta:
        dataclass = InternalEvent


def internal_event_to_dict(data: InternalEvent) -> dict:
    return InternalEventSerializer(data).data


def create_internal_event(
    team_id: int, event: InternalEventEvent, person: Optional[InternalEventPerson] = None
) -> InternalEvent:
    data = InternalEvent(team_id=team_id, event=event, person=person)

    if data.event.uuid is None:
        data.event.uuid = str(uuid.uuid4())
    if data.event.timestamp is None:
        data.event.timestamp = datetime.now(UTC).isoformat()

    return data


def produce_internal_event(
    team_id: int, event: InternalEventEvent, person: Optional[InternalEventPerson] = None
) -> ProduceResult:
    data = create_internal_event(team_id, event, person)
    serialized_data = internal_event_to_dict(data)
    kafka_topic = KAFKA_CDP_INTERNAL_EVENTS

    try:
        producer = get_producer(topic=kafka_topic)
        return producer.produce(topic=kafka_topic, data=serialized_data, key=data.event.uuid)
    except Exception as e:
        # Identify the event by ids, not payload: properties can carry credentials
        # (e.g. tokenized delivery URLs) and person data, which must not reach logs.
        logger.exception(
            "Failed to produce internal event",
            team_id=team_id,
            event_name=data.event.event,
            event_uuid=data.event.uuid,
            error=e,
        )
        raise


def flush_internal_events_producer(timeout: float) -> int:
    """Block until previously produced internal events are delivered (or `timeout`
    elapses), returning the number still undelivered. A zero only means all
    delivery callbacks have fired, not that they all succeeded — check each
    `ProduceResult` for per-message outcomes."""
    return get_producer(topic=KAFKA_CDP_INTERNAL_EVENTS).flush(timeout)

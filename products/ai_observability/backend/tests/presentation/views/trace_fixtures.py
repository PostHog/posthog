import base64
from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.event_definitions.backend.models.property_definition import PropertyDefinition

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

GENERATION = "00000000-0000-0000-0000-000000000001"
TRACE_EVENT = "00000000-0000-0000-0000-000000000002"
QUESTION = [{"role": "user", "content": "Why did my invoice go up?"}]
ANSWER = [{"role": "assistant", "content": "Two seats were added."}]


def create_trace(team: Team, trace_id: str = "trace-1", *, extra_properties: dict[str, object] | None = None) -> None:
    bulk_create_ai_events(
        [
            {
                "event": "$ai_generation",
                "event_uuid": "00000000-0000-0000-0000-000000000001",
                "distinct_id": "user-1",
                "team": team,
                "timestamp": T0,
                "properties": {
                    "$ai_trace_id": trace_id,
                    "$ai_parent_id": trace_id,
                    "$ai_input_tokens": 3,
                    **(extra_properties or {}),
                },
            }
        ]
    )


def create_node_trace(
    team: Team,
    trace_id: str = "trace-1",
    *,
    with_trace_event: bool = True,
    extra_properties: dict[str, object] | None = None,
) -> None:
    events: list[dict[str, object]] = [
        {
            "event": "$ai_generation",
            "event_uuid": GENERATION,
            "distinct_id": "user-1",
            "team": team,
            "timestamp": T0,
            "properties": {
                "$ai_trace_id": trace_id,
                "$ai_parent_id": trace_id,
                "$ai_input": QUESTION,
                "$ai_output_choices": ANSWER,
                "$ai_tools": [{"name": "lookup_invoice"}],
                "$ai_provider": "openai",
                **(extra_properties or {}),
            },
        }
    ]
    if with_trace_event:
        events.append(
            {
                "event": "$ai_trace",
                "event_uuid": TRACE_EVENT,
                "distinct_id": "user-1",
                "team": team,
                "timestamp": T0,
                "properties": {"$ai_trace_id": trace_id, "$ai_input_state": {"question": "Why?"}},
            }
        )
    bulk_create_ai_events(events)


class TraceEvents:
    """Events written to both `ai_events` and the shared `events` table, each with its own uuid, so that a list
    selects its traces on one table and reads their rows from the other."""

    def __init__(self, team: Team, *, start: datetime = T0) -> None:
        self.team = team
        self.start = start
        self._events: list[dict[str, object]] = []

    def add(
        self,
        trace_id: str,
        *,
        event: str = "$ai_generation",
        minutes: int = 0,
        properties: dict[str, object] | None = None,
        person_id: str | None = None,
    ) -> None:
        self._events.append(
            {
                "event": event,
                "event_uuid": f"00000000-0000-4000-8000-{len(self._events):012d}",
                "distinct_id": "user-1",
                "team": self.team,
                "timestamp": self.start + timedelta(minutes=minutes),
                "properties": {"$ai_trace_id": trace_id, "$ai_parent_id": trace_id, **(properties or {})},
                **({"person_id": person_id} if person_id is not None else {}),
            }
        )

    def seed(self) -> None:
        bulk_create_events(self._events)
        bulk_create_ai_events(self._events)

    def seed_traces(self, *trace_ids: str) -> None:
        for minutes, trace_id in enumerate(trace_ids):
            self.add(trace_id, minutes=minutes)
        self.seed()


def restrict_property(test: APIBaseTest, name: str) -> None:
    test.organization.available_product_features = [
        {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
    ]
    test.organization.save()
    definition = PropertyDefinition.objects.create(
        team=test.team, name=name, property_type="String", type=PropertyDefinition.Type.EVENT
    )
    PropertyAccessControl.objects.create(
        team=test.team,
        property_definition=definition,
        organization_member=test.organization_membership,
        access_level=PropertyAccessLevel.NONE.value,
    )


def encode_segment(trace_id: str) -> str:
    return base64.urlsafe_b64encode(trace_id.encode()).decode().rstrip("=")

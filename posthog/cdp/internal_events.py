import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import structlog
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_CDP_INTERNAL_EVENTS

logger = structlog.get_logger(__name__)


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
        data.event.timestamp = datetime.now().isoformat()

    return data


def produce_internal_event(team_id: int, event: InternalEventEvent, person: Optional[InternalEventPerson] = None):
    data = create_internal_event(team_id, event, person)
    serialized_data = internal_event_to_dict(data)
    kafka_topic = KAFKA_CDP_INTERNAL_EVENTS

    try:
        producer = KafkaProducer()
        future = producer.produce(topic=kafka_topic, data=serialized_data, key=data.event.uuid)
        future.get()
    except Exception as e:
        logger.exception("Failed to produce internal event", data=serialized_data, error=e)
        raise

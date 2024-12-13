from typing import Union

from kafka import TopicPartition
from rest_framework import serializers, viewsets
from posthog.api.utils import action
from rest_framework.response import Response

from posthog.kafka_client.client import build_kafka_consumer
from posthog.permissions import IsStaffUser

KAFKA_CONSUMER_TIMEOUT = 1000


# the kafka package doesn't expose ConsumerRecord
class KafkaConsumerRecord:
    topic: str
    partition: int
    offset: int
    timestamp: int
    key: str
    value: Union[dict, str]

    def __init__(self, topic, partition, offset, timestamp, key, value):
        self.topic = topic
        self.partition = partition
        self.offset = offset
        self.value = value
        self.timestamp = timestamp
        self.key = key


class KafkaMessageSerializer(serializers.Serializer):
    topic = serializers.CharField(read_only=True)
    partition = serializers.IntegerField(read_only=True)
    offset = serializers.IntegerField(read_only=True)
    timestamp = serializers.IntegerField(read_only=True)
    key = serializers.CharField(read_only=True)
    value = serializers.JSONField(read_only=True)


class KafkaInspectorViewSet(viewsets.ViewSet):
    permission_classes = [IsStaffUser]

    @action(methods=["POST"], detail=False)
    def fetch_message(self, request):
        topic = request.data.get("topic", None)
        partition = request.data.get("partition", None)
        offset = request.data.get("offset", None)

        if not isinstance(topic, str):
            return Response({"error": "Invalid topic."}, status=400)

        if not isinstance(partition, int):
            return Response({"error": "Invalid partition."}, status=400)

        if not isinstance(offset, int):
            return Response({"error": "Invalid offset."}, status=400)

        try:
            message = get_kafka_message(topic, partition, offset)
            serializer = KafkaMessageSerializer(message, context={"request": request})
            return Response(serializer.data)
        except AssertionError:
            return Response({"error": "Invalid partition/offset pair."}, status=400)
        except StopIteration:
            return Response(
                {
                    "error": f"Error reading message, most likely the consumer timed out after {KAFKA_CONSUMER_TIMEOUT}ms."
                },
                status=400,
            )
        except Exception as e:
            return Response({"error": e.__str__()}, status=500)


def get_kafka_message(topic: str, partition: int, offset: int) -> KafkaConsumerRecord:
    consumer = build_kafka_consumer(
        topic=None,
        auto_offset_reset="earliest",
        group_id="kafka-inspector",
        consumer_timeout_ms=KAFKA_CONSUMER_TIMEOUT,
    )

    consumer.assign([TopicPartition(topic, partition)])
    consumer.seek(partition=TopicPartition(topic, partition), offset=offset)

    message = next(consumer)

    return message

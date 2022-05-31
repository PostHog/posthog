from typing import List

from django.core.management.base import BaseCommand
from kafka import KafkaAdminClient
from kafka.errors import TopicAlreadyExistsError

from ee.kafka_client.client import _KafkaSecurityProtocol
from ee.kafka_client.helper import get_kafka_brokers, get_kafka_ssl_context
from ee.kafka_client.topic_definitions import TopicDefinition
from ee.kafka_client.topics import KAFKA_TOPIC_DEFINITIONS
from posthog.settings.data_stores import KAFKA_SECURITY_PROTOCOL


def create_kafka_topics(kafka_admin_client: KafkaAdminClient, topic_definitions: List[TopicDefinition]):
    topics = [topic_definition.get_new_topic_definition() for topic_definition in topic_definitions]
    created_topics: List[str] = []
    existing_topics: List[str] = []
    missing_topics: List[str] = []
    for topic in topics:
        try:
            kafka_admin_client.create_topics([topic])
            created_topics.append(topic.name)
        except TopicAlreadyExistsError:
            print(f"Topic {topic.name} already exists. Skipping creation...\n")
            existing_topics.append(topic.name)
        except Exception as e:
            print(f"Could not create topic {topic.name} with error: {e.__str__()}")
            missing_topics.append(topic.name)

    created_topics_str = ", ".join(created_topics)
    existing_topics_str = ", ".join(existing_topics)
    missing_topics_str = ", ".join(missing_topics)
    print(
        f"Created topics: {created_topics_str}\nAlready existing topics: {existing_topics_str}\nMissing topics: {missing_topics_str}\n"
    )

    if len(missing_topics) > 0:
        print("Some topics are missing! PostHog may not work correctly.")


class Command(BaseCommand):
    help = "Set up databases for non-Python tests that depend on the Django server"

    def handle(self, *args, **options):
        admin_client = KafkaAdminClient(
            bootstrap_servers=get_kafka_brokers(),
            security_protocol=KAFKA_SECURITY_PROTOCOL or _KafkaSecurityProtocol.PLAINTEXT,
            ssl_context=get_kafka_ssl_context() if KAFKA_SECURITY_PROTOCOL is not None else None,
        )

        create_kafka_topics(admin_client, KAFKA_TOPIC_DEFINITIONS)

# This management command is intended to be used to migrate data from one Kafka
# cluster to another. It is intended for the use case where the Kafka cluster
# has suffered some catastrophic failure that causes us to migrate to a new
# cluster. The old cluster may well come back up, and in which case we would
# want to ensure that if there is any data in the old cluster that wasn't
# consumed by the PostHog app when it was pointing at it, then that data is
# transferred to the new cluster.
#
# We do not make any attempt at validation, so it's important to ensure that you
# move data to and from the corresponding topics.
#
# We also do not validate that you use the correct consumer group ID, so it's
# important that you use the same consumer group ID that the PostHog app is
# using when consuming from the old cluster, otherwise you risk migrating data
# that has already been consumed.
#
# By default the target Kafka cluster is the currently configured cluster in
# Django settings.

from django.core.management.base import BaseCommand
from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
from kafka.structs import TopicPartition

from django.conf import settings


class Command(BaseCommand):
    help = "Migrate data from one Kafka cluster to another"

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-topic",
            required=True,
            help="The topic to migrate data from",
        )
        parser.add_argument(
            "--to-topic",
            required=True,
            help="The topic to migrate data to",
        )
        parser.add_argument(
            "--from-cluster",
            default=settings.KAFKA_URL,
            help="The Kafka cluster to migrate data from",
        )
        parser.add_argument(
            "--to-cluster",
            default=settings.KAFKA_URL,
            help="The Kafka cluster to migrate data to",
        )
        parser.add_argument(
            "--consumer-group-id",
            default="posthog",
            help="The consumer group ID to use when consuming from the old cluster",
        )

    def handle(self, *args, **options):
        from_topic = options["from_topic"]
        to_topic = options["to_topic"]
        from_cluster = options["from_cluster"]
        to_cluster = options["to_cluster"]
        consumer_group_id = options["consumer_group_id"]

        # Validate that we don't push messages back into the same cluster and
        # topic.
        if from_cluster == to_cluster and from_topic == to_topic:
            raise ValueError("You must specify a different topic and cluster to migrate data to")

        # Using the Kafka Admin API, make sure the specified consumer group
        # already has offsets committed for the topic we're migrating data from.
        # If it doesn't, then we do not want to try to migrate data as we expect
        # that if called correctly, we would be specifying a consumer group ID
        # that has already been consuming from the cluster.
        admin_client = KafkaAdminClient(bootstrap_servers=from_cluster)
        try:
            committed_offsets = admin_client.list_consumer_group_offsets(consumer_group_id)
        except KafkaError as e:
            raise ValueError(f"Failed to list consumer group offsets: {e}")

        if not committed_offsets:
            raise ValueError(f"Consumer group {consumer_group_id} has no committed offsets")

        if TopicPartition(topic=from_topic, partition=0) not in committed_offsets:
            raise ValueError(
                f"Consumer group {consumer_group_id} has no committed offsets for topic {from_topic}: {committed_offsets}"
            )

        self.stdout.write(
            f"Migrating data from topic {from_topic} on cluster {from_cluster} to topic {to_topic} on cluster {to_cluster} using consumer group ID {consumer_group_id}"
        )

        # Create a Kafka consumer to consume from the old topic.
        consumer = KafkaConsumer(
            from_topic,
            bootstrap_servers=from_cluster,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            group_id=consumer_group_id,
            consumer_timeout_ms=1000,
        )

        # Create a Kafka producer to produce to the new topic.
        producer = KafkaProducer(bootstrap_servers=to_cluster)

        # Now consume from the consumer, and produce to the producer.
        while True:
            self.stdout.write("Polling for messages")
            messages_by_topic = consumer.poll(timeout_ms=10)

            if not messages_by_topic:
                break

            # Send the messages to the new topic. Note that messages may not be
            # send immediately, but rather batched by the Kafka Producer
            # according to e.g. linger_ms etc.
            for topic, messages in messages_by_topic.items():
                self.stdout.write(f"Sending {len(messages)} messages to topic {topic}")
                for message in messages:
                    producer.send(
                        to_topic,
                        message.value,
                        key=message.key,
                        headers=message.headers,
                    )

            # Commit the offsets for the messages we just consumed.
            self.stdout.write("Committing offsets")
            consumer.commit()

        self.stdout.write("Flushing producer")
        producer.flush()

        self.stdout.write("Done migrating data")

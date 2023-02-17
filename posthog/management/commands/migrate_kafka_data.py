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

from typing import List

from django.core.management.base import BaseCommand
from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
from kafka.producer.future import FutureRecordMetadata
from kafka.structs import TopicPartition


class Command(BaseCommand):
    help = "Migrate data from one Kafka cluster to another"

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-topic",
            required=True,
            help="The topic to migrate data from",
        )
        parser.add_argument(
            "--from-cluster",
            help="The Kafka cluster to migrate data from",
        )
        parser.add_argument(
            "--from-cluster-security-protocol",
            default="PLAINTEXT",
            help="The security protocol to use when connecting to the old cluster",
        )
        parser.add_argument(
            "--to-topic",
            required=True,
            help="The topic to migrate data to",
        )
        parser.add_argument(
            "--to-cluster",
            help="The Kafka cluster to migrate data to",
        )
        parser.add_argument(
            "--to-cluster-security-protocol",
            default="PLAINTEXT",
            help="The security protocol to use when connecting to the new cluster",
        )
        parser.add_argument(
            "--consumer-group-id",
            required=True,
            help="The consumer group ID to use when consuming from the old cluster",
        )
        parser.add_argument(
            "--linger-ms",
            default=1000,
            help="The number of milliseconds to wait before sending a batch of messages to the new cluster",
        )
        parser.add_argument(
            "--batch-size",
            default=1000 * 1000,
            help="The maximum number of bytes per partition to send in a batch of messages to the new cluster",
        )

    def handle(self, *args, **options):
        from_topic = options["from_topic"]
        to_topic = options["to_topic"]
        from_cluster = options["from_cluster"]
        to_cluster = options["to_cluster"]
        consumer_group_id = options["consumer_group_id"]
        linger_ms = options["linger_ms"]
        batch_size = options["batch_size"]
        from_cluster_security_protocol = options["from_cluster_security_protocol"]
        to_cluster_security_protocol = options["to_cluster_security_protocol"]

        # Validate that we don't push messages back into the same cluster and
        # topic.
        if from_cluster == to_cluster and from_topic == to_topic:
            raise ValueError("You must specify a different topic and cluster to migrate data to")

        # Fail if the to_topic doesn't exist
        admin_client = KafkaAdminClient(bootstrap_servers=to_cluster, security_protocol=to_cluster_security_protocol)
        topics_response = admin_client.describe_topics([to_topic])
        if not list(topics_response) or topics_response[0]["error_code"]:
            raise ValueError(f"Topic {to_topic} does not exist")

        # Using the Kafka Admin API, make sure the specified consumer group
        # already has offsets committed for the topic we're migrating data from.
        # If it doesn't, then we do not want to try to migrate data as we expect
        # that if called correctly, we would be specifying a consumer group ID
        # that has already been consuming from the cluster.
        admin_client = KafkaAdminClient(
            bootstrap_servers=from_cluster, security_protocol=from_cluster_security_protocol
        )
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
            auto_offset_reset="latest",
            enable_auto_commit=False,
            group_id=consumer_group_id,
            consumer_timeout_ms=1000,
            security_protocol=from_cluster_security_protocol,
        )

        # Create a Kafka producer to produce to the new topic.
        producer = KafkaProducer(
            bootstrap_servers=to_cluster,
            linger_ms=linger_ms,
            batch_size=batch_size,
            security_protocol=to_cluster_security_protocol,
        )

        # Get all the partitions for the topic we're migrating data from.
        partitions = consumer.partitions_for_topic(from_topic)
        assert partitions, "No partitions found for topic"

        # Get the latest offsets for all the partitions of the topic we're
        # migrating data from.
        latest_offsets = consumer.end_offsets(
            [TopicPartition(topic=from_topic, partition=partition) for partition in partitions]
        )
        assert latest_offsets, "No latest offsets found for topic"

        # Calculate the current lag for the consumer group.
        current_lag = sum(
            latest_offsets[TopicPartition(topic=from_topic, partition=partition)]
            - committed_offsets[TopicPartition(topic=from_topic, partition=partition)].offset
            for partition in partitions
        )

        try:
            # Now consume from the consumer, and produce to the producer.
            while True:
                self.stdout.write("Polling for messages")
                messages_by_topic = consumer.poll(timeout_ms=1000)

                futures: List[FutureRecordMetadata] = []

                if not messages_by_topic:
                    break

                # Send the messages to the new topic. Note that messages may not be
                # send immediately, but rather batched by the Kafka Producer
                # according to e.g. linger_ms etc.
                for topic, messages in messages_by_topic.items():
                    self.stdout.write(f"Sending {len(messages)} messages to topic {topic}")
                    for message in messages:
                        futures.append(
                            producer.send(
                                to_topic,
                                message.value,
                                key=message.key,
                                headers=message.headers,
                            )
                        )

                # Flush the producer to ensure that all messages are sent.
                self.stdout.write("Flushing producer")
                producer.flush()
                for future in futures:
                    future.get()

                # Commit the offsets for the messages we just consumed.
                self.stdout.write("Committing offsets")
                consumer.commit()

                # Report the original offset lag, the current offset lag, and
                # the percentage of the original offset lag that has been
                # migrated.
                new_lag = sum(
                    latest_offsets[TopicPartition(topic=from_topic, partition=partition)]
                    - consumer.position(TopicPartition(topic=from_topic, partition=partition))
                    for partition in partitions
                )

                self.stdout.write(
                    f"Original lag: {current_lag}, current lag: {new_lag}, migrated: {100 - (new_lag / current_lag * 100):.2f}%"
                )

        finally:
            # Close the consumer and producer.
            self.stdout.write("Closing consumer")
            consumer.close()
            self.stdout.write("Closing producer")
            producer.close()

        self.stdout.write("Done migrating data")

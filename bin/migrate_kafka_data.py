#!/usr/bin/env python3
#
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

import sys
import argparse

from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
from kafka.producer.future import FutureRecordMetadata
from kafka.structs import TopicPartition

help = "Migrate data from one Kafka cluster to another"


def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--from-topic",
        required=True,
        help="The topic to migrate data from",
    )
    parser.add_argument(
        "--from-cluster",
        required=True,
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
        required=True,
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
        type=int,
        help="The number of milliseconds to wait before sending a batch of messages to the new cluster",
    )
    parser.add_argument(
        "--batch-size",
        default=1000 * 1000,
        type=int,
        help="The maximum number of bytes per partition to send in a batch of messages to the new cluster",
    )
    parser.add_argument(
        "--timeout-ms",
        default=1000 * 10,
        type=int,
        help="The maximum number of milliseconds to wait for a batch from the old cluster before timing out",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not actually migrate any data or commit any offsets, just print the number of messages that would be migrated",
    )
    return parser


def handle(**options):
    from_topic = options["from_topic"]
    to_topic = options["to_topic"]
    from_cluster = options["from_cluster"]
    to_cluster = options["to_cluster"]
    consumer_group_id = options["consumer_group_id"]
    linger_ms = options["linger_ms"]
    batch_size = options["batch_size"]
    from_cluster_security_protocol = options["from_cluster_security_protocol"]
    to_cluster_security_protocol = options["to_cluster_security_protocol"]
    dry_run = options["dry_run"]
    timeout_ms = options["timeout_ms"]

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
    admin_client = KafkaAdminClient(bootstrap_servers=from_cluster, security_protocol=from_cluster_security_protocol)
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

    print(  # noqa: T201
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

    try:
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

        print(f"Current lag for consumer group {consumer_group_id} is {current_lag}")  # noqa: T201

        if dry_run:
            print("Dry run, not migrating any data or committing any offsets")  # noqa: T201
            return
        else:
            print("Migrating data")  # noqa: T201

        # Now consume from the consumer, and produce to the producer.
        while True:
            print("Polling for messages")  # noqa: T201
            messages_by_topic = consumer.poll(timeout_ms=timeout_ms)

            futures: list[FutureRecordMetadata] = []

            if not messages_by_topic:
                break

            # Send the messages to the new topic. Note that messages may not be
            # send immediately, but rather batched by the Kafka Producer
            # according to e.g. linger_ms etc.
            for topic, messages in messages_by_topic.items():
                print(f"Sending {len(messages)} messages to topic {topic}")  # noqa: T201
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
            print("Flushing producer")  # noqa: T201
            producer.flush()
            for future in futures:
                future.get()

            # Commit the offsets for the messages we just consumed.
            print("Committing offsets")  # noqa: T201
            consumer.commit()

            # Report the original offset lag, the current offset lag, and
            # the percentage of the original offset lag that has been
            # migrated.
            new_lag = sum(
                latest_offsets[TopicPartition(topic=from_topic, partition=partition)]
                - consumer.position(TopicPartition(topic=from_topic, partition=partition))
                for partition in partitions
            )

            print(  # noqa: T201
                f"Original lag: {current_lag}, current lag: {new_lag}, migrated: {100 - (new_lag / current_lag * 100):.2f}%"
            )

    finally:
        # Close the consumer and producer.
        print("Closing consumer")  # noqa: T201
        consumer.close()
        print("Closing producer")  # noqa: T201
        producer.close()

    print("Done migrating data")  # noqa: T201


def run(*args):
    parser = get_parser()
    args = parser.parse_args(args)
    handle(**vars(args))


if __name__ == "__main__":
    run(*sys.argv[1:])

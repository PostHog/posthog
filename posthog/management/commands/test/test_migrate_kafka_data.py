from uuid import uuid4

from unittest import mock

from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer
from kafka.admin.new_topic import NewTopic
from kafka.errors import KafkaError
from kafka.producer.future import FutureProduceResult, FutureRecordMetadata
from kafka.structs import TopicPartition

from bin.migrate_kafka_data import run as migrate_kafka_data


def test_can_migrate_data_from_one_topic_to_another_on_a_different_cluster():
    """
    Importantly, we want to make sure:

        1. we commit offsets to the old cluster, such that we do not produce
           duplicates on e.g. multiple runs
        2. we do not commit offsets to the new cluster
        3. we do not produce to the old cluster
        4. we copy over not just the values of the messages, but also the keys

    """
    old_events_topic = str(uuid4())
    new_events_topic = str(uuid4())
    consumer_group_id = "events-ingestion-consumer"
    message_key = str(uuid4())

    # The command will fail if we don't have a consumer group ID that has
    # already committed offsets to the old topic, so we need to commit some
    # offsets first.
    _commit_offsets_for_topic(old_events_topic, consumer_group_id)

    _create_topic(new_events_topic)

    # Put some data to the old topic
    _send_message(
        old_events_topic,
        b'{ "event": "test" }',
        key=message_key.encode("utf-8"),
        headers=[("foo", b"bar")],
    )

    migrate_kafka_data(
        "--from-topic",
        old_events_topic,
        "--to-topic",
        new_events_topic,
        "--from-cluster",
        "localhost:9092",
        "--to-cluster",
        "localhost:9092",
        "--consumer-group-id",
        consumer_group_id,
        # Include all the options so we check they can be passed in
        "--linger-ms",
        "0",
        "--batch-size",
        "100",
        "--timeout-ms",
        "1000",
    )

    # We should have produced a message to the new topic
    found_message = _wait_for_message(new_events_topic, message_key)

    assert found_message and found_message.value == b'{ "event": "test" }', "Did not find message in new topic"
    assert found_message and found_message.headers == [("foo", b"bar")], "Did not find headers in new topic"

    # Try running the command again, and we should't see a new message produced
    migrate_kafka_data(
        "--from-topic",
        old_events_topic,
        "--to-topic",
        new_events_topic,
        "--from-cluster",
        "localhost:9092",
        "--to-cluster",
        "localhost:9092",
        "--consumer-group-id",
        consumer_group_id,
    )

    found_message = _wait_for_message(new_events_topic, message_key)
    assert not found_message


def test_we_do_not_migrate_when_dry_run_is_set():
    """
    We want to make sure that we do not migrate data when the dry run flag is
    set.
    """
    old_events_topic = str(uuid4())
    new_events_topic = str(uuid4())
    consumer_group_id = "events-ingestion-consumer"
    message_key = str(uuid4())

    _commit_offsets_for_topic(old_events_topic, consumer_group_id)

    _create_topic(new_events_topic)

    # Put some data to the old topic
    _send_message(
        old_events_topic,
        b'{ "event": "test" }',
        key=message_key.encode("utf-8"),
        headers=[("foo", b"bar")],
    )

    migrate_kafka_data(
        "--from-topic",
        old_events_topic,
        "--to-topic",
        new_events_topic,
        "--from-cluster",
        "localhost:9092",
        "--to-cluster",
        "localhost:9092",
        "--consumer-group-id",
        consumer_group_id,
        "--dry-run",
    )

    # We should not have produced a message to the new topic
    found_message = _wait_for_message(new_events_topic, message_key)
    assert not found_message


def test_cannot_send_data_back_into_same_topic_on_same_cluster():
    """
    We want to make sure that we do not send data back into the same topic on
    the same cluster, as that would cause duplicates.
    """
    topic = str(uuid4())
    consumer_group_id = "events-ingestion-consumer"
    message_key = str(uuid4())

    _commit_offsets_for_topic(topic, consumer_group_id)

    # Put some data to the topic
    _send_message(
        topic,
        b'{ "event": "test" }',
        key=message_key.encode("utf-8"),
        headers=[("foo", b"bar")],
    )

    try:
        migrate_kafka_data(
            "--from-topic",
            topic,
            "--to-topic",
            topic,
            "--from-cluster",
            "localhost:9092",
            "--to-cluster",
            "localhost:9092",
            "--consumer-group-id",
            consumer_group_id,
        )
    except ValueError as e:
        assert str(e) == "You must specify a different topic and cluster to migrate data to"
    else:
        raise AssertionError("Expected ValueError to be raised")


def test_that_the_command_fails_if_the_specified_consumer_group_does_not_exist():
    """
    We want to make sure that the command fails if the specified consumer group
    does not exist for the topic.
    """
    old_topic = str(uuid4())
    new_topic = str(uuid4())
    message_key = str(uuid4())

    _create_topic(new_topic)

    # Put some data to the topic
    _send_message(
        old_topic,
        b'{ "event": "test" }',
        key=message_key.encode("utf-8"),
        headers=[("foo", b"bar")],
    )

    try:
        migrate_kafka_data(
            "--from-topic",
            old_topic,
            "--to-topic",
            new_topic,
            "--from-cluster",
            "localhost:9092",
            "--to-cluster",
            "localhost:9092",
            "--consumer-group-id",
            "nonexistent-consumer-group",
        )
    except ValueError as e:
        assert str(e) == "Consumer group nonexistent-consumer-group has no committed offsets"
    else:
        raise AssertionError("Expected ValueError to be raised")


def test_that_we_error_if_the_target_topic_doesnt_exist():
    """
    We want to make sure that the command fails if the target topic does not
    exist.
    """
    old_topic = str(uuid4())
    new_topic = str(uuid4())
    consumer_group_id = "events-ingestion-consumer"
    message_key = str(uuid4())

    _commit_offsets_for_topic(old_topic, consumer_group_id)

    # Put some data to the topic
    _send_message(
        old_topic,
        b'{ "event": "test" }',
        key=message_key.encode("utf-8"),
        headers=[("foo", b"bar")],
    )

    try:
        migrate_kafka_data(
            "--from-topic",
            old_topic,
            "--to-topic",
            new_topic,
            "--from-cluster",
            "localhost:9092",
            "--to-cluster",
            "localhost:9092",
            "--consumer-group-id",
            consumer_group_id,
        )
    except ValueError as e:
        assert str(e) == f"Topic {new_topic} does not exist"
    else:
        raise AssertionError("Expected ValueError to be raised")


def test_we_fail_on_send_errors_to_new_topic():
    """
    We want to make sure that we fail if we get an error when sending data to
    the new topic.
    """
    old_topic = str(uuid4())
    new_topic = str(uuid4())
    consumer_group_id = "events-ingestion-consumer"
    message_key = str(uuid4())

    _create_topic(new_topic)

    _commit_offsets_for_topic(old_topic, consumer_group_id)

    # Put some data to the topic
    _send_message(
        old_topic,
        b'{ "event": "test" }',
        key=message_key.encode("utf-8"),
        headers=[("foo", b"bar")],
    )

    with mock.patch("kafka.KafkaProducer.send") as mock_send:
        produce_future = FutureProduceResult(topic_partition=TopicPartition(new_topic, 1))
        future = FutureRecordMetadata(
            produce_future=produce_future,
            relative_offset=0,
            timestamp_ms=0,
            checksum=0,
            serialized_key_size=0,
            serialized_value_size=0,
            serialized_header_size=0,
        )
        future.failure(KafkaError("Failed to produce"))
        mock_send.return_value = future

        try:
            migrate_kafka_data(
                "--from-topic",
                old_topic,
                "--to-topic",
                new_topic,
                "--from-cluster",
                "localhost:9092",
                "--to-cluster",
                "localhost:9092",
                "--consumer-group-id",
                consumer_group_id,
            )
        except KafkaError as e:
            assert str(e) == "KafkaError: Failed to produce"
        else:
            raise AssertionError("Expected KafkaError to be raised")

    # Ensure that if we run the command again, it will not fail
    # and will re-consume and produce the message to the new topic.
    migrate_kafka_data(
        "--from-topic",
        old_topic,
        "--to-topic",
        new_topic,
        "--from-cluster",
        "localhost:9092",
        "--to-cluster",
        "localhost:9092",
        "--consumer-group-id",
        consumer_group_id,
    )

    found_message = _wait_for_message(new_topic, message_key)

    assert found_message, "Did not find message in new topic"


def _commit_offsets_for_topic(topic, consumer_group_id):
    kafka_consumer = KafkaConsumer(
        topic,
        bootstrap_servers="localhost:9092",
        auto_offset_reset="latest",
        group_id=consumer_group_id,
    )

    try:
        kafka_consumer.poll(timeout_ms=1000)
        kafka_consumer.commit()

    finally:
        kafka_consumer.close()


def _wait_for_message(topic: str, key: str):
    """
    Wait for a message to appear in the topic with the specified key.
    """
    new_kafka_consumer = KafkaConsumer(
        topic,
        bootstrap_servers="localhost:9092",
        auto_offset_reset="earliest",
        group_id="test",
    )

    try:
        messages_by_topic = new_kafka_consumer.poll(timeout_ms=1000)

        if not messages_by_topic:
            return

        for _, messages in messages_by_topic.items():
            for message in messages:
                if message.key.decode("utf-8") == key:
                    return message

    finally:
        new_kafka_consumer.close()


def _send_message(topic, value, key, headers):
    producer = KafkaProducer(bootstrap_servers="localhost:9092")

    try:
        producer.send(topic, value, key, headers).get()

    finally:
        producer.close()


def _create_topic(topic):
    admin_client = KafkaAdminClient(bootstrap_servers="localhost:9092")

    try:
        admin_client.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])

    finally:
        admin_client.close()

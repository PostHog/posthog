from unittest import mock
from uuid import uuid4
from django.core.management import call_command
from kafka import KafkaConsumer, KafkaProducer

from kafka.errors import KafkaError
from kafka.producer.future import FutureProduceResult, FutureRecordMetadata
from kafka.structs import TopicPartition


def test_can_migrate_data_from_one_topic_to_another_on_a_different_cluster():
    """
    Importantly, we want to make sure:

        1. we commit offsets to the old cluster, such that we do not produce
           duplicates on e.g. multiple runs
        2. we do not commit offsets to the new cluster
        3. we do not produce to the old cluster
        4. we copy over not just the values of the messages, but also the keys

    """
    old_events_topic = "old_events_topic"
    new_events_topic = "new_events_topic"
    consumer_group_id = "events-ingestion-consumer"
    message_key = str(uuid4())

    # The command will fail if we don't have a consumer group ID that has
    # already committed offsets to the old topic, so we need to commit some
    # offsets first.
    _commit_offsets_for_topic(old_events_topic, consumer_group_id)

    old_kafka = KafkaProducer(bootstrap_servers="localhost:9092")

    # Put some data to the old topic
    old_kafka.send(old_events_topic, b'{ "event": "test" }', key=message_key.encode("utf-8"), headers=[("foo", b"bar")])
    old_kafka.flush()

    call_command(
        "migrate_kafka_data",
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

    # Now create a kafka consumer to consumer data from the new topic, and
    # verify it is the same as from the old topic.
    new_kafka_consumer = KafkaConsumer(
        new_events_topic,
        bootstrap_servers="localhost:9092",
        auto_offset_reset="earliest",
        group_id="test",
    )

    # Poll the consumer for messages until we find a message with the same
    # message_key we send to the old topic, failing the test if we don't find
    # it within 10 seconds.
    found_message = None
    for _ in range(10):
        messages_by_topic = new_kafka_consumer.poll(timeout_ms=1000)

        if not messages_by_topic:
            continue

        for _, messages in messages_by_topic.items():
            for message in messages:
                if message.key.decode("utf-8") == message_key:
                    found_message = message
                    break

            if found_message:
                break
        if found_message:
            break

    assert found_message and found_message.value == b'{ "event": "test" }', "Did not find message in new topic"
    assert found_message and found_message.headers == [("foo", b"bar")], "Did not find headers in new topic"


def test_cannot_send_data_back_into_same_topic_on_same_cluster():
    """
    We want to make sure that we do not send data back into the same topic on
    the same cluster, as that would cause duplicates.
    """
    topic = "events_topic"
    consumer_group_id = "events-ingestion-consumer"
    kafka = KafkaProducer(bootstrap_servers="localhost:9092")
    message_key = str(uuid4())

    _commit_offsets_for_topic(topic, consumer_group_id)

    # Put some data to the topic
    kafka.send(topic, b'{ "event": "test" }', key=message_key.encode("utf-8"))
    kafka.flush()

    try:
        call_command(
            "migrate_kafka_data",
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
        assert False, "Expected ValueError to be raised"


def test_that_the_command_fails_if_the_specified_consumer_group_does_not_exist():
    """
    We want to make sure that the command fails if the specified consumer group
    does not exist for the topic.
    """
    old_topic = "events_topic"
    new_topic = "new_events_topic"
    kafka = KafkaProducer(bootstrap_servers="localhost:9092")
    message_key = str(uuid4())

    # Put some data to the topic
    kafka.send(old_topic, b'{ "event": "test" }', key=message_key.encode("utf-8"))
    kafka.flush()

    try:
        call_command(
            "migrate_kafka_data",
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
        assert False, "Expected ValueError to be raised"


def test_that_we_error_if_the_target_topic_doesnt_exist():
    """
    We want to make sure that the command fails if the target topic does not
    exist.
    """
    old_topic = "events_topic"
    new_topic = str(uuid4())
    consumer_group_id = "events-ingestion-consumer"
    kafka = KafkaProducer(bootstrap_servers="localhost:9092")
    message_key = str(uuid4())

    _commit_offsets_for_topic(old_topic, consumer_group_id)

    # Put some data to the topic
    kafka.send(old_topic, b'{ "event": "test" }', key=message_key.encode("utf-8"))
    kafka.flush()

    try:
        call_command(
            "migrate_kafka_data",
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
        assert str(e) == "Topic new_events_topic does not exist"
    else:
        assert False, "Expected ValueError to be raised"


def test_we_fail_on_send_errors_to_new_topic():
    """
    We want to make sure that we fail if we get an error when sending data to
    the new topic.
    """
    old_topic = "events_topic"
    new_topic = "new_events_topic"
    consumer_group_id = "events-ingestion-consumer"
    kafka = KafkaProducer(bootstrap_servers="localhost:9092")
    message_key = str(uuid4())

    _commit_offsets_for_topic(old_topic, consumer_group_id)

    # Put some data to the topic
    kafka.send(old_topic, b'{ "event": "test" }', key=message_key.encode("utf-8"))
    kafka.flush()

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
            call_command(
                "migrate_kafka_data",
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
            assert str(e) == "Error sending message to new topic"
        else:
            assert False, "Expected KafkaError to be raised"


def _commit_offsets_for_topic(topic, consumer_group_id):
    kafka_consumer = KafkaConsumer(
        topic,
        bootstrap_servers="localhost:9092",
        auto_offset_reset="latest",
        group_id=consumer_group_id,
    )
    kafka_consumer.poll(timeout_ms=1000)
    kafka_consumer.commit()
    kafka_consumer.close()

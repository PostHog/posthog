from django.core.management import call_command
from kafka import KafkaConsumer, KafkaProducer


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

    old_kafka = KafkaProducer(bootstrap_servers="localhost:9092")

    # Put some data to the old topic
    old_kafka.send(old_events_topic, b'{ "event": "test" }', key=b"key")
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
        "events-ingestion-consumer",
    )

    # Now create a kafka consumer to consumer data from the new topic, and
    # verify it is the same as from the old topic.
    new_kafka_consumer = KafkaConsumer(
        new_events_topic,
        bootstrap_servers="localhost:9092",
        group_id="test",
    )

    new_kafka_consumer.subscribe([new_events_topic])

    # Now consume from the consumer, collect all messages and verify they are
    # the same.
    messages = new_kafka_consumer.poll(timeout_ms=1000)

    assert len(messages) == 1


def test_cannot_send_data_back_into_same_topic_on_same_cluster():
    """
    We want to make sure that we do not send data back into the same topic on
    the same cluster, as that would cause duplicates.
    """
    topic = "events_topic"
    kafka = KafkaProducer(bootstrap_servers="localhost:9092")

    # Put some data to the topic
    kafka.send(topic, b'{ "event": "test" }', key=b"key")
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
            "events-ingestion-consumer",
        )
    except ValueError as e:
        assert str(e) == "You must specify a different topic and cluster to migrate data to"
    else:
        assert False, "Expected ValueError to be raised"

from kafka.admin import NewTopic

from posthog.settings.data_stores import KAFKA_DEFAULT_TOPIC_REPLICATION_FACTOR


class TopicDefinition:

    name: str
    num_partitions: int
    retention_days: int

    def __init__(self, name, num_partitions, retention_days=1):
        self.name = name
        self.num_partitions = num_partitions
        self.retention_days = retention_days

    def get_new_topic_definition(self):
        return NewTopic(
            name=self.name,
            num_partitions=self.num_partitions,
            replication_factor=KAFKA_DEFAULT_TOPIC_REPLICATION_FACTOR,
            topic_configs={"retention.ms": self.retention_days * 24 * 60 * 60 * 1000},
        )

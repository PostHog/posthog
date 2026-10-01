from posthog.clickhouse.kafka_engine import kafka_engine

COHORT_MEMBERSHIP_TABLE = "cohort_membership"

COHORT_MEMBERSHIP_KAFKA_TABLE = f"kafka_{COHORT_MEMBERSHIP_TABLE}"


def KAFKA_COHORT_MEMBERSHIP_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    `team_id` Int64,
    `cohort_id` Int64,
    `person_id` UUID,
    `status` Enum8('entered' = 1, 'left' = 2, 'member' = 3, 'not_member' = 4),
    `last_updated` DateTime64(6)
) ENGINE = {engine}
""".format(
        table_name=COHORT_MEMBERSHIP_KAFKA_TABLE,
        engine=kafka_engine(topic="cohort_membership_changed", group="clickhouse_cohort_membership_changed"),
    )

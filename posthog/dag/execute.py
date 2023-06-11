from posthog.client import sync_execute
from pathlib import Path
from datetime import datetime
from typing import Optional
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta

path = Path(__file__, "..").resolve()


class DAG:
    def person_distinct_id_table(
        self, from_timestamp: Optional[datetime] = None, until_timestamp: Optional[datetime] = None
    ):
        if not until_timestamp:
            until_timestamp = now() + relativedelta(seconds=200)
        with open(path.joinpath("person_distinct_id.sql"), "r") as r:
            # sync_execute(r)
            self._execute(r.read(), from_timestamp, until_timestamp)

    def person_table(self, from_timestamp: Optional[datetime] = None, until_timestamp: Optional[datetime] = None):
        if not until_timestamp:
            until_timestamp = now()
        with open(path.joinpath("person.sql"), "r") as r:

            self._execute(r.read(), from_timestamp, until_timestamp)

    def set_up(self):
        sync_execute(
            "create table posthog_dag.person AS posthog_test.person engine=ReplacingMergeTree order by (team_id, id)"
        )
        sync_execute(
            """
        CREATE TABLE posthog_dag.person_distinct_id
        (
            `team_id` Int64,
            `distinct_id` String,
            `person_id` String,
            `is_deleted` Int8,
            `version` Int64 DEFAULT 1,
            `is_identified` bool DEFAULT 0,
            `_timestamp` DateTime,
            `_offset` UInt64,
            `_partition` UInt64,
            INDEX kafka_timestamp_minmax_person_distinct_id2 _timestamp TYPE minmax GRANULARITY 3
        )
        ENGINE = ReplacingMergeTree
        ORDER BY (team_id, distinct_id)
        """
        )

    def _execute(self, sql: str, from_timestamp: Optional[datetime], until_timestamp: datetime):
        params = {"until_timestamp": until_timestamp}
        timestamp_sql = " _timestamp <= %(until_timestamp)s"

        if from_timestamp:
            timestamp_sql += " AND _timestamp >= %(from_timestamp)s"
            params["from_timestamp"] = from_timestamp
        return sync_execute(sql.format(timestamp_sql=timestamp_sql), params)

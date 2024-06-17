from posthog.clickhouse.client import sync_execute
from posthog.test.base import APIBaseTest, QueryMatchingTest, ClickhouseTestMixin, _create_event
from posthog.error_tracking.test import embedding_test_data

exception_type = "example"


class TestErrorTrackingEmbeddings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def test_can_something(self) -> None:
        sync_execute("drop table if exists error_events")
        sync_execute("drop view if exists error_events_mv")

        # a destination table for events
        sync_execute("""
        create table if not exists error_events
        (
            event_id UUID,
            team_id int,
            session_id String,
            timestamp timestamp,
            `$exception_message` String,
            `$embeddings` Array(Float32),
            properties String
        ) engine ReplacingMergeTree()
        PARTITION BY toYYYYMM(timestamp)
        ORDER BY (toStartOfDay(timestamp), team_id, session_id, event_id)
        """)

        # and the MV to select into it
        sync_execute("""
        create materialized view if not exists error_events_mv
to error_events
as
select
    uuid as event_id,
    team_id,
    `$session_id` as session_id,
    timestamp,
    JSONExtractString(properties, '$exception_message') as `$exception_message`,
    JSONExtract(properties, '$embeddings', 'Array(Nullable(Float32))') as `$embeddings`,
    properties
from
    sharded_events
where
    `$session_id` IS NOT NULL AND `$session_id` != ''
    AND JSONHas(properties, '$exception_message')
    AND JSONHas(properties, '$embeddings')
        """)

        sync_execute("""
        ALTER TABLE error_events
        ADD INDEX ann_embedding_idx `$embeddings` TYPE usearch('L2Distance') GRANULARITY 1;
        """)

        # sync_execute("""
        #     ALTER TABLE sharded_events
        #     ADD COLUMN IF NOT EXISTS `$mat_embedding` Array(Nullable(Float32)) MATERIALIZED
        #         if(
        #             JSONHas(properties, '$embeddings'),
        #             JSONExtract(properties, '$embeddings', 'Array(Nullable(Float32))'),
        #             arrayResize([], 1024, null) -- all the arrays in the column need to be the same length - wat
        #         )
        # """)

        # sync_execute("""
        #     ALTER TABLE sharded_events
        #     ADD INDEX IF NOT EXISTS ann_embedding_idx `$mat_embedding` TYPE usearch('L2Distance') GRANULARITY 1;
        #     """)

        for data in embedding_test_data:
            _create_event(
                event="$exception",
                team=self.team,
                distinct_id="distinct_id",
                properties={
                    "$exception_message": data[0],
                    "$embeddings": data[1],
                    "$session_id": "session_id",
                },
            )

        # this insert gives "clickhouse DB::Exception: All arrays in column '$mat_embedding' must have equal length"
        _create_event(
            event="some other type of event that has no embeddings",
            team=self.team,
            distinct_id="distinct_id",
            properties={"something": "else", "$session_id": "session_id"},
        )

        # messages = sync_execute("SELECT JSONExtractString(properties, '$exception_message') FROM events")
        # assert sorted(messages) == sorted(
        #     [
        #         ('',),
        #         (
        #             "Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!",
        #         ),
        #         (
        #             "Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!",
        #         ),
        #         ("That Sam-Iam!",),
        #         ("TypeError: Cannot read property 'do not have a cow' of undefined",),
        #         ("I am Sam.",),
        #         ("I do not like that Sam-I-am!",),
        #         ("In the far light and darkness",),
        #         ("TypeError: Cannot read property 'len' of undefined",),
        #         ("That Sam-Iam!",),
        #         ("TypeError: Cannot read property 'l' of undefined",),
        #         (
        #             "Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!",
        #         ),
        #         ("Sam I am.",),
        #         (
        #             "Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!",
        #         ),
        #         (
        #             "In the quiet moments between the stars, where the light of distant suns barely touched the darkness, he found a sense of peace, a momentary respite from the endless, chaotic dance of existence.",
        #         ),
        #         ("TypeError: Cannot read property 'length' of undefined",),
        #         ("In the quite distant cars, where the light barely touched the darkness",),
        #         (
        #             "In the quiet moments between the cars, where the light of the nearby store barely touched the darkness, he found a sense of peace, a momentary respite from the endless, chaotic dance of existence.",
        #         ),
        #     ]
        # )

        event_errors = sync_execute("""WITH distances AS (
    SELECT
        t1.event_id AS id1,
        t2.event_id AS id2,
        L2Distance(t1.`$embeddings`, t2.`$embeddings`) AS distance
    FROM
        (SELECT event_id, $embeddings, properties FROM error_events
         WHERE timestamp >= now() - INTERVAL 1 day) AS t1
        CROSS JOIN (SELECT event_id, $embeddings, properties FROM error_events
                    WHERE timestamp >= now() - INTERVAL 1 day) AS t2
    WHERE
        t1.event_id < t2.event_id
),
thresholds AS (
    SELECT
        id1,
        id2,
        distance,
        ROW_NUMBER() OVER (PARTITION BY id1 ORDER BY distance) AS rnum
    FROM
        distances
),
clusters AS (
    SELECT
        id1,
        arrayJoin(groupArray(id2)) AS cluster_member
    FROM
        thresholds
    WHERE
        distance < 10 -- Replace with an appropriate threshold
    GROUP BY
        id1
)
SELECT
    id1 as cluster,
    groupArray(error_events.$exception_message) as messages
FROM
    clusters
    JOIN error_events ON clusters.cluster_member = error_events.event_id
group by id1""")
        breakpoint()
        assert event_errors == ["wat"]

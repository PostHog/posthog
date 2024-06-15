from posthog.clickhouse.client import sync_execute
from posthog.test.base import APIBaseTest, QueryMatchingTest, ClickhouseTestMixin, _create_event
from posthog.error_tracking.test import embedding_test_data

exception_type = "example"


class TestErrorTrackingEmbeddings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def test_can_something(self) -> None:
        sync_execute("""
            ALTER TABLE sharded_events
            ADD COLUMN IF NOT EXISTS `$mat_embedding` Array(Nullable(Float32)) MATERIALIZED
                if(
                    JSONHas(properties, '$embeddings'),
                    JSONExtract(properties, '$embeddings', 'Array(Nullable(Float32))'),
                    arrayResize([], 1024, null) -- all the arrays in the column need to be the same length - wat
                )
        """)

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
                },
            )

        # this insert gives "clickhouse DB::Exception: All arrays in column '$mat_embedding' must have equal length"
        # _create_event(
        #     event="some other type of event that has no embeddings",
        #     team=self.team,
        #     distinct_id="distinct_id",
        #     properties={"something": "else"}
        # )

        wat = sync_execute("""
        show table events
            """)
        assert "$mat_embedding" in wat[0][0]

        messages = sync_execute("SELECT JSONExtractString(properties, '$exception_message') FROM events")
        assert sorted(messages) == sorted(
            [
                ("",),
                (
                    "Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!",
                ),
                (
                    "Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!",
                ),
                ("That Sam-Iam!",),
                ("TypeError: Cannot read property 'do not have a cow' of undefined",),
                ("I am Sam.",),
                ("I do not like that Sam-I-am!",),
                ("In the far light and darkness",),
                ("TypeError: Cannot read property 'len' of undefined",),
                ("That Sam-Iam!",),
                ("TypeError: Cannot read property 'l' of undefined",),
                (
                    "Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!",
                ),
                ("Sam I am.",),
                (
                    "Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!",
                ),
                (
                    "In the quiet moments between the stars, where the light of distant suns barely touched the darkness, he found a sense of peace, a momentary respite from the endless, chaotic dance of existence.",
                ),
                ("TypeError: Cannot read property 'length' of undefined",),
                ("In the quite distant cars, where the light barely touched the darkness",),
                (
                    "In the quiet moments between the cars, where the light of the nearby store barely touched the darkness, he found a sense of peace, a momentary respite from the endless, chaotic dance of existence.",
                ),
            ]
        )

        embeddings = sync_execute("SELECT $mat_embedding FROM events")
        assert len(embeddings) == len(messages)

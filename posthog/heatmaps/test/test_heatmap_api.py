import math
from typing import Dict
from unittest import skip

import freezegun
from django.http import HttpResponse

from posthog.heatmaps.sql import INSERT_SINGLE_HEATMAP_EVENT
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest, snapshot_clickhouse_queries


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _assert_heatmap_no_result_count(self, params: Dict[str, str | int] | None) -> None:
        response = self._get_heatmap(params)
        assert len(response.json()["results"]) == 0

    def _assert_heatmap_single_result_count(
        self, params: Dict[str, str | int] | None, expected_grouped_count: int
    ) -> None:
        response = self._get_heatmap(params)
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["count"] == expected_grouped_count

    def _get_heatmap(self, params: Dict[str, str | int] | None) -> HttpResponse:
        if params is None:
            params = {}

        query_params = "&".join([f"{key}={value}" for key, value in params.items()])
        response = self.client.get(f"/api/heatmap/?{query_params}")
        assert response.status_code == 200, response.json()

        return response

    @snapshot_clickhouse_queries
    def test_can_get_empty_response(self) -> None:
        response = self.client.get("/api/heatmap/?date_from=2024-05-03")
        assert response.status_code == 200
        self.assertEqual(response.json(), {"results": []})

    @snapshot_clickhouse_queries
    def test_can_get_all_data_response(self) -> None:
        self._create_heatmap_event("session_1", "click")
        self._create_heatmap_event("session_2", "click")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08"}, 2)

    @snapshot_clickhouse_queries
    def test_can_get_filter_by_date_from(self) -> None:
        self._create_heatmap_event("session_1", "click", "2023-03-07T07:00:00")
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08"}, 1)

    @snapshot_clickhouse_queries
    @freezegun.freeze_time("2023-03-14T09:00:00")
    @skip(
        "running this gives an error posthog.hogql.errors.ResolutionError: SQLValueEscaper has no method visit_fakedate"
    )
    def test_can_get_filter_by_relative_date_from(self) -> None:
        self._create_heatmap_event("session_1", "click", "2023-03-07T07:00:00")
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00")

        self._assert_heatmap_single_result_count({"date_from": "-7d"}, 1)

    @snapshot_clickhouse_queries
    def test_can_get_filter_by_click(self) -> None:
        self._create_heatmap_event("session_1", "click", "2023-03-08T07:00:00")
        self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:00:00")
        self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:01:00")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "type": "click"}, 1)

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "type": "rageclick"}, 2)

    @snapshot_clickhouse_queries
    def test_can_filter_by_exact_url(self) -> None:
        self._create_heatmap_event("session_1", "rageclick", "2023-03-08T08:00:00", current_url="http://example.com")
        self._create_heatmap_event(
            "session_2", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com/about"
        )
        self._create_heatmap_event(
            "session_3", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com/about"
        )

        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "url_exact": "http://example.com", "type": "rageclick"}, 1
        )

        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "url_exact": "http://example.com/about", "type": "rageclick"}, 2
        )

        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "url_pattern": "http://example.com*", "type": "rageclick"}, 3
        )

    @snapshot_clickhouse_queries
    def test_can_get_scrolldepth_counts(self) -> None:
        self._create_heatmap_event("session_1", "scrolldepth", "2023-03-08T07:00:00", y=10, viewport_height=1000)
        self._create_heatmap_event("session_2", "scrolldepth", "2023-03-08T08:00:00", y=100, viewport_height=1000)
        self._create_heatmap_event("session_3", "scrolldepth", "2023-03-08T08:01:00", y=200, viewport_height=1000)
        self._create_heatmap_event("session_4", "scrolldepth", "2023-03-08T08:01:00", y=300, viewport_height=1000)
        self._create_heatmap_event("session_5", "scrolldepth", "2023-03-08T08:01:00", y=400, viewport_height=1000)
        self._create_heatmap_event("session_6", "scrolldepth", "2023-03-08T08:01:00", y=500, viewport_height=1000)
        self._create_heatmap_event("session_7", "scrolldepth", "2023-03-08T08:01:00", y=900, viewport_height=1000)
        self._create_heatmap_event("session_8", "scrolldepth", "2023-03-08T08:01:00", y=900, viewport_height=1000)

        scroll_response = self._get_heatmap({"date_from": "2023-03-06", "type": "scrolldepth"})

        assert scroll_response.json() == {
            "results": [
                {
                    "bucket_count": 1,
                    "cumulative_count": 8,
                    "scroll_depth_bucket": 1000,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 7,
                    "scroll_depth_bucket": 1100,
                },
                {
                    "bucket_count": 2,
                    "cumulative_count": 6,
                    "scroll_depth_bucket": 1200,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 4,
                    "scroll_depth_bucket": 1400,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 3,
                    "scroll_depth_bucket": 1500,
                },
                {
                    "bucket_count": 2,
                    "cumulative_count": 2,
                    "scroll_depth_bucket": 1900,
                },
            ],
        }

    @snapshot_clickhouse_queries
    def test_can_get_filter_by_min_viewport(self) -> None:
        # all scale to 10
        self._create_heatmap_event("session_1", "click", "2023-03-08T08:00:00", 150)
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00", 151)
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 152)
        # scale to 11
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 161)
        # scales to 12
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 177)

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "viewport_width_min": "150"}, 5)
        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "viewport_width_min": "161"}, 2)
        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "viewport_width_min": "177"}, 1)
        self._assert_heatmap_no_result_count({"date_from": "2023-03-08", "viewport_width_min": "193"})

    @snapshot_clickhouse_queries
    def test_can_get_filter_by_min_and_max_viewport(self) -> None:
        # all scale to 10
        self._create_heatmap_event("session_1", "click", "2023-03-08T08:00:00", 150)
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00", 151)
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 152)
        # scale to 11
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 161)
        # scales to 12
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 177)
        # scales to 13
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 193)

        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "viewport_width_min": 161, "viewport_width_max": 192}, 2
        )

    @snapshot_clickhouse_queries
    def test_can_get_count_by_aggregation(self) -> None:
        # 3 items but 2 viitors
        self._create_heatmap_event("session_1", "click", distinct_id="12345")
        self._create_heatmap_event("session_2", "click", distinct_id="12345")
        self._create_heatmap_event("session_3", "click", distinct_id="54321")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08"}, 3)
        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "aggregation": "unique_visitors"}, 2)

    def test_can_get_scrolldepth_counts_by_visitor(self) -> None:
        self._create_heatmap_event(
            "session_1", "scrolldepth", "2023-03-08T07:00:00", y=100, viewport_height=1000, distinct_id="12345"
        )
        # one person only scrolls a little way
        self._create_heatmap_event(
            "session_2", "scrolldepth", "2023-03-08T08:00:00", y=100, viewport_height=1000, distinct_id="34567"
        )
        self._create_heatmap_event(
            "session_3", "scrolldepth", "2023-03-08T08:01:00", y=200, viewport_height=1000, distinct_id="12345"
        )

        scroll_response = self._get_heatmap(
            {"date_from": "2023-03-06", "type": "scrolldepth", "aggregation": "unique_visitors"}
        )

        assert scroll_response.json() == {
            "results": [
                {
                    "bucket_count": 2,
                    "cumulative_count": 3,
                    "scroll_depth_bucket": 1100,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 1,
                    "scroll_depth_bucket": 1200,
                },
            ],
        }

    def _create_heatmap_event(
        self,
        session_id: str,
        type: str,
        date_from: str = "2023-03-08T09:00:00",
        viewport_width: int = 100,
        viewport_height: int = 100,
        y: int = 20,
        current_url: str | None = None,
        distinct_id: str = "user_distinct_id",
    ) -> None:
        p = ClickhouseProducer()
        # because this is in a test it will write directly using SQL not really with Kafka
        p.produce(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
            sql=INSERT_SINGLE_HEATMAP_EVENT,
            data={
                "session_id": session_id,
                "team_id": self.team.pk,
                "distinct_id": distinct_id,
                "timestamp": format_clickhouse_timestamp(date_from),
                "x": 10 / 16,
                "y": y / 16,
                "scale_factor": 16,
                # this adjustment is done at ingestion
                "viewport_width": math.ceil(viewport_width / 16),
                "viewport_height": math.ceil(viewport_height / 16),
                "type": type,
                "pointer_target_fixed": True,
                "current_url": current_url if current_url else "http://posthog.com",
            },
        )

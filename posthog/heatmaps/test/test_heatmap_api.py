import math
from typing import Dict

from posthog.heatmaps.sql import INSERT_SINGLE_HEATMAP_EVENT
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest, snapshot_clickhouse_queries


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _assert_heatmap_single_result_count(self, params: Dict[str, str] | None, expected_grouped_count: int) -> None:
        if params is None:
            params = {}

        query_params = "&".join([f"{key}={value}" for key, value in params.items()])

        response = self.client.get(f"/api/heatmap/?{query_params}")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["count"] == expected_grouped_count

    @snapshot_clickhouse_queries
    def test_can_get_empty_response(self) -> None:
        response = self.client.get("/api/heatmap/")
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
    def test_can_get_filter_by_click(self) -> None:
        self._create_heatmap_event("session_1", "click", "2023-03-08T07:00:00")
        self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:00:00")
        self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:01:00")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "type": "click"}, 1)

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "type": "rageclick"}, 2)

    # @snapshot_clickhouse_queries
    # def test_can_get_filter_by_viewport(self) -> None:
    #     self._create_heatmap_event("session_1", "click", "2023-03-08T08:00:00", 150)
    #     self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:00:00", 151)
    #     self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:01:00", 152)
    #
    #     self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "viewport_width_min": "150"}, 3)
    #     self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "viewport_width_min": "151"}, 1)
    #     self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "viewport_width_min": "152"}, 1)
    #     self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "viewport_width_min": "153"}, 1)

    def _create_heatmap_event(
        self, session_id: str, type: str, date_from: str = "2023-03-08T09:00:00", viewport_width: int = 100
    ) -> None:
        p = ClickhouseProducer()
        # because this is in a test it will write directly using SQL not really with Kafka
        p.produce(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
            sql=INSERT_SINGLE_HEATMAP_EVENT,
            data={
                "session_id": session_id,
                "team_id": self.team.pk,
                "timestamp": format_clickhouse_timestamp(date_from),
                "x": 10,
                "y": 20,
                "scale_factor": 16,
                # this adjustment is done at ingestion
                "viewport_width": math.ceil(viewport_width / 16),
                "viewport_height": math.ceil(100 / 16),
                "type": type,
                "pointer_target_fixed": True,
                "current_url": "http://example.com",
            },
        )

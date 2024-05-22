import freezegun
from django.http import HttpResponse
from parameterized import parameterized
from rest_framework import status

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models import Organization, Team
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest, snapshot_clickhouse_queries


INSERT_SINGLE_HEATMAP_EVENT = """
INSERT INTO sharded_heatmaps (
    session_id,
    team_id,
    distinct_id,
    timestamp,
    x,
    y,
    scale_factor,
    viewport_width,
    viewport_height,
    pointer_target_fixed,
    current_url,
    type
)
SELECT
    %(session_id)s,
    %(team_id)s,
    %(distinct_id)s,
    %(timestamp)s,
    %(x)s,
    %(y)s,
    %(scale_factor)s,
    %(viewport_width)s,
    %(viewport_height)s,
    %(pointer_target_fixed)s,
    %(current_url)s,
    %(type)s
"""


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _assert_heatmap_no_result_count(
        self, params: dict[str, str | int | None] | None, expected_status_code: int = status.HTTP_200_OK
    ) -> None:
        response = self._get_heatmap(params, expected_status_code)
        if response.status_code == status.HTTP_200_OK:
            assert len(response.json()["results"]) == 0

    def _assert_heatmap_single_result_count(
        self, params: dict[str, str | int | None] | None, expected_grouped_count: int
    ) -> None:
        response = self._get_heatmap(params)
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["count"] == expected_grouped_count

    def _get_heatmap(
        self, params: dict[str, str | int | None] | None, expected_status_code: int = status.HTTP_200_OK
    ) -> HttpResponse:
        if params is None:
            params = {}

        query_params = "&".join([f"{key}={value}" for key, value in params.items()])
        response = self.client.get(f"/api/heatmap/?{query_params}")
        assert response.status_code == expected_status_code, response.json()

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

    def test_cannot_query_across_teams(self) -> None:
        self._create_heatmap_event("session_1", "click")
        self._create_heatmap_event("session_2", "click")

        org = Organization.objects.create(name="Separate Org")
        other_team = Team.objects.create(organization=org, name="other orgs team")
        self._create_heatmap_event("session_1", "click", team_id=other_team.pk)

        # second team's click is not counted
        self._assert_heatmap_single_result_count({"date_from": "2023-03-08"}, 2)

    @snapshot_clickhouse_queries
    def test_can_get_filter_by_date_from(self) -> None:
        self._create_heatmap_event("session_1", "click", "2023-03-07T07:00:00")
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08"}, 1)

    @snapshot_clickhouse_queries
    @freezegun.freeze_time("2023-03-15T09:00:00")
    def test_can_get_filter_by_relative_date(self) -> None:
        self._create_heatmap_event("session_1", "click", "2023-03-07T07:00:00")
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00")

        self._assert_heatmap_single_result_count({"date_from": "-7d", "date_to": "-1d"}, 1)
        self._assert_heatmap_no_result_count({"date_from": "dStart", "date_to": "dEnd"})

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

    @snapshot_clickhouse_queries
    def test_can_filter_by_url_pattern_where_end_is_anchored(self) -> None:
        # home page with no trailing slash
        self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com")

        # home page with trailing slash
        self._create_heatmap_event(
            "session_1",
            "rageclick",
            "2023-03-08T08:00:00",
            current_url="http://example.com/",
        )

        # should match nothing, no trailing slash
        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "url_pattern": "http://example.com", "type": "rageclick"}, 1
        )

    @parameterized.expand(
        [
            ["http://example.com*", 6],
            ["http://example.com/products*", 5],
            ["http://example.com/products/1*", 2],
            ["http://example.com/products/*/reviews/*", 2],
            ["http://example.com/products/*/parts/*", 2],
            ["http://example.com/products/1*/parts/*", 1],
        ],
        name_func=lambda f, n, p: f"{f.__name__}_{p.args[0]}",
    )
    @snapshot_clickhouse_queries
    def test_can_filter_by_url_pattern(self, pattern: str, expected_matches: int) -> None:
        # the home page
        self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com/")

        # a product page with a review
        self._create_heatmap_event(
            "session_1",
            "rageclick",
            "2023-03-08T08:00:00",
            current_url="http://example.com/products/12345/reviews/4567",
        )

        # a different product page with a review
        self._create_heatmap_event(
            "session_1", "rageclick", "2023-03-08T08:00:00", current_url="http://example.com/products/3456/reviews/defg"
        )

        # all reviews for one product
        self._create_heatmap_event(
            "session_1", "rageclick", "2023-03-08T08:00:00", current_url="http://example.com/products/3456/reviews/"
        )

        # the same product but a different sub-route
        self._create_heatmap_event(
            "session_3", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com/products/12345/parts/abcd"
        )

        # a different product that shares a part
        self._create_heatmap_event(
            "session_3", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com/products/3456/parts/abcd"
        )

        # should match nothing, no trailing slash
        self._assert_heatmap_no_result_count(
            {"date_from": "2023-03-08", "url_pattern": "http://example.com", "type": "rageclick"}
        )

        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "url_pattern": pattern, "type": "rageclick"},
            expected_matches,
        )

    @snapshot_clickhouse_queries
    def test_can_get_scrolldepth_counts(self) -> None:
        # to calculate expected scroll depth bucket from y and viewport height
        # ((round(y/16) + round(viewport_height/16)) * 16 // 100) * 100

        # scroll depth bucket 1000
        self._create_heatmap_event("session_1", "scrolldepth", "2023-03-08T07:00:00", y=10, viewport_height=1000)
        self._create_heatmap_event("session_2", "scrolldepth", "2023-03-08T08:00:00", y=100, viewport_height=1000)
        # scroll depth bucket 1100
        self._create_heatmap_event("session_3", "scrolldepth", "2023-03-08T08:01:00", y=200, viewport_height=1000)
        # scroll depth bucket 1200
        self._create_heatmap_event("session_4", "scrolldepth", "2023-03-08T08:01:00", y=300, viewport_height=1000)
        # scroll depth bucket 1300
        self._create_heatmap_event("session_5", "scrolldepth", "2023-03-08T08:01:00", y=400, viewport_height=1000)
        # scroll depth bucket 1400
        self._create_heatmap_event("session_6", "scrolldepth", "2023-03-08T08:01:00", y=500, viewport_height=1000)
        # scroll depth bucket 1800
        self._create_heatmap_event("session_7", "scrolldepth", "2023-03-08T08:01:00", y=900, viewport_height=1000)
        self._create_heatmap_event("session_8", "scrolldepth", "2023-03-08T08:01:00", y=900, viewport_height=1000)

        scroll_response = self._get_heatmap({"date_from": "2023-03-06", "type": "scrolldepth"})

        assert scroll_response.json() == {
            "results": [
                {
                    "bucket_count": 2,
                    "cumulative_count": 8,
                    "scroll_depth_bucket": 1000,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 6,
                    "scroll_depth_bucket": 1100,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 5,
                    "scroll_depth_bucket": 1200,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 4,
                    "scroll_depth_bucket": 1300,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 3,
                    "scroll_depth_bucket": 1400,
                },
                {
                    "bucket_count": 2,
                    "cumulative_count": 2,
                    "scroll_depth_bucket": 1800,
                },
            ],
        }

    def test_can_get_scrolldepth_counts_by_visitor(self) -> None:
        # scroll depth bucket 1000
        self._create_heatmap_event(
            "session_1", "scrolldepth", "2023-03-08T07:00:00", y=100, viewport_height=1000, distinct_id="12345"
        )

        # one person only scrolls a little way
        # scroll depth bucket 1000
        self._create_heatmap_event(
            "session_2", "scrolldepth", "2023-03-08T08:00:00", y=100, viewport_height=1000, distinct_id="34567"
        )

        # the first person scrolls further
        # scroll depth bucket 1100
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
                    "scroll_depth_bucket": 1000,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 1,
                    "scroll_depth_bucket": 1100,
                },
            ],
        }

    @staticmethod
    def heatmap_result(relative_x: float, count: int) -> dict:
        return {
            "count": count,
            "pointer_relative_x": relative_x,
            "pointer_target_fixed": True,
            "pointer_y": 16,
        }

    @parameterized.expand(
        [
            [
                "min_150",
                {"date_from": "2023-03-08", "viewport_width_min": "150"},
                [heatmap_result(0.08, 1), heatmap_result(0.09, 1), heatmap_result(0.1, 1), heatmap_result(0.11, 2)],
            ],
            [
                "min_161",
                {"date_from": "2023-03-08", "viewport_width_min": "161"},
                [
                    heatmap_result(0.08, 1),
                    heatmap_result(0.09, 1),
                    heatmap_result(0.1, 1),
                ],
            ],
            [
                "min_177",
                {"date_from": "2023-03-08", "viewport_width_min": "177"},
                [
                    heatmap_result(0.08, 1),
                    heatmap_result(0.09, 1),
                ],
            ],
            ["min_201", {"date_from": "2023-03-08", "viewport_width_min": "201"}, []],
            [
                "min_161_and_max_192",
                {"date_from": "2023-03-08", "viewport_width_min": 161, "viewport_width_max": 192},
                [heatmap_result(0.08, 1), heatmap_result(0.09, 1), heatmap_result(0.1, 1)],
            ],
        ]
    )
    @snapshot_clickhouse_queries
    def test_can_filter_by_viewport(self, _name: str, query_params: dict, expected_results: list) -> None:
        # all these xs = round(10/16) = 1

        # viewport widths that scale to 9
        self._create_heatmap_event("session_1", "click", "2023-03-08T08:00:00", 150)
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00", 151)

        # viewport widths that scale to 10
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 152)
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 161)

        # viewport width that scales to 11
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 177)
        # viewport width that scales to 12
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 193)

        response = self._get_heatmap(query_params)
        assert sorted(response.json()["results"], key=lambda k: k["pointer_relative_x"]) == expected_results

    @snapshot_clickhouse_queries
    def test_can_get_count_by_aggregation(self) -> None:
        # 3 items but 2 visitors
        self._create_heatmap_event("session_1", "click", distinct_id="12345")
        self._create_heatmap_event("session_2", "click", distinct_id="12345")
        self._create_heatmap_event("session_3", "click", distinct_id="54321")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08"}, 3)
        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "aggregation": "unique_visitors"}, 2)

    @parameterized.expand(
        [
            ["total_count", status.HTTP_200_OK],
            ["unique_visitors", status.HTTP_200_OK],
            ["direction", status.HTTP_400_BAD_REQUEST],
            # equivalent to not providing it
            ["", status.HTTP_200_OK],
            ["     ", status.HTTP_400_BAD_REQUEST],
            [None, status.HTTP_400_BAD_REQUEST],
        ]
    )
    def test_only_allow_valid_values_for_aggregation(self, choice: str | None, expected_status_code: int) -> None:
        self._assert_heatmap_no_result_count(
            {"date_from": "2023-03-08", "aggregation": choice}, expected_status_code=expected_status_code
        )

    def _create_heatmap_event(
        self,
        session_id: str,
        type: str,
        date_from: str = "2023-03-08T09:00:00",
        viewport_width: int = 100,
        viewport_height: int = 100,
        x: int = 10,
        y: int = 20,
        current_url: str | None = None,
        distinct_id: str = "user_distinct_id",
        team_id: int | None = None,
    ) -> None:
        if team_id is None:
            team_id = self.team.pk

        p = ClickhouseProducer()
        # because this is in a test it will write directly using SQL not really with Kafka
        p.produce(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
            sql=INSERT_SINGLE_HEATMAP_EVENT,
            data={
                "session_id": session_id,
                "team_id": team_id,
                "distinct_id": distinct_id,
                "timestamp": format_clickhouse_timestamp(date_from),
                "x": round(x / 16),
                "y": round(y / 16),
                "scale_factor": 16,
                # this adjustment is done at ingestion
                "viewport_width": round(viewport_width / 16),
                "viewport_height": round(viewport_height / 16),
                "type": type,
                "pointer_target_fixed": True,
                "current_url": current_url if current_url else "http://posthog.com",
            },
        )

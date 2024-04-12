from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest, snapshot_clickhouse_queries


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    @snapshot_clickhouse_queries
    def test_can_get_empty_response(self) -> None:
        response = self.client.get("/api/heatmap/")
        assert response.status_code == 200
        self.assertEqual(response.json(), {"results": []})

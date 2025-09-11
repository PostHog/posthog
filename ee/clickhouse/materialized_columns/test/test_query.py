from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    def test_get_queries_detects(self):
        # some random
        with self.capture_select_queries() as queries:
            self.client.post(
                f"/api/projects/{self.team.id}/insights/funnel/",
                {
                    "events": [{"id": "step one", "type": "events", "order": 0}],
                    "funnel_window_days": 14,
                    "funnel_order_type": "unordered",
                    "insight": "funnels",
                },
            ).json()

        self.assertTrue(len(queries))

        # make sure that the queries start with a discoverable prefix.
        # If this changes, also update ee/clickhouse/materialized_columns/analyze.py::_get_queries to
        # filter on the right queries
        for q in queries:
            self.assertTrue(q.startswith("/* user_id"))

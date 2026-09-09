from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    def test_get_queries_detects(self):
        # some random
        with self.capture_select_queries() as queries:
            self.client.post(
                f"/api/projects/{self.team.id}/query/",
                {
                    "query": {
                        "kind": "FunnelsQuery",
                        "series": [
                            {"kind": "EventsNode", "event": "step one"},
                            {"kind": "EventsNode", "event": "step two"},
                        ],
                        "funnelsFilter": {"funnelOrderType": "unordered"},
                    }
                },
            ).json()

        self.assertTrue(len(queries))

        # make sure that the queries start with a discoverable prefix.
        # If this changes, also update ee/clickhouse/materialized_columns/analyze.py::_get_queries to
        # filter on the right queries
        for q in queries:
            self.assertTrue(q.startswith("/* user_id"))

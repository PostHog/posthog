from posthog.hogql_queries.runners.lifecycle_runner import LifecycleQueryRunner

from posthog.schema import LifecycleQuery
from posthog.test.base import BaseTest

data = {
    "kind": "LifecycleQuery",
    "series": [{"kind": "EventsNode", "name": "$pageview", "event": "$pageview", "math": "total"}],
    "lifecycleFilter": {"shown_as": "Lifecycle"},
    "filterTestAccounts": False,
}


class TestRunner(BaseTest):
    def test_to_dict(self):
        query = LifecycleQuery.parse_obj(data)

        runner = LifecycleQueryRunner(query=query, team=self.team)

        self.assertEqual(runner.to_dict(), {"filter_test_accounts": True})

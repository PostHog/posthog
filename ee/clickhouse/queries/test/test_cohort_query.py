from ee.clickhouse.queries.cohort_query import CohortQuery
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.filters.filter import Filter
from posthog.test.base import BaseTest


class TestCohortQuery(ClickhouseTestMixin, BaseTest):
    def test_basic_query(self):
        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "event",
                            "time_value": 1,
                            "time_interval": "day",
                            "type": "performed_event",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "event",
                            "time_value": 2,
                            "time_interval": "week",
                            "type": "performed_event",
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()

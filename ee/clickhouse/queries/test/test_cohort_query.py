from ee.clickhouse.queries.cohort_query import CohortQuery
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters.filter import Filter
from posthog.test.base import BaseTest


class TestCohortQuery(ClickhouseTestMixin, BaseTest):
    def test_basic_query(self):

        action1 = Action.objects.create(team=self.team, name="action1")
        step1 = ActionStep.objects.create(
            event="$autocapture", action=action1, url="https://posthog.com/feedback/123", url_matching=ActionStep.EXACT,
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
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
                        {
                            "key": action1.pk,
                            "event_type": "action",
                            "time_value": 2,
                            "time_interval": "week",
                            "type": "performed_event_first_time",
                        },
                        {"key": "email", "value": "test@posthog.com", "type": "person"},
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()

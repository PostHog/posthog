from typing import Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from posthog.models import Filter
from posthog.queries.trends.trends import Trends
from posthog.test.test_journeys import journeys_for

BREAKDOWN_OTHER_DISPLAY = "Other (i.e. all remaining values)"


class TestPagingBreakdowns(APIBaseTest):
    """
    A test to explore a report from a customer
    https://posthog.slack.com/archives/C02LR7352SG/p1643738897887099
    """

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()

        # create 2 pages of events each with a unique property
        with freeze_time("2020-01-02T13:01:01Z"):
            journeys_for(
                events_by_person={
                    "p1": [
                        {
                            "team": self.team,
                            "event": "$pageview",
                            "distinct_id": "blabla",
                            "properties": {"wildcard_route": f"/1/*/{i}"},
                        }
                        for i in range(50)
                    ]
                },
                team=self.team,
                create_people=True,
            )

    def _run(self, extra: Optional[dict] = None, run_at: Optional[str] = None):
        if extra is None:
            extra = {}
        with freeze_time(run_at or "2020-01-04T13:01:01Z"):
            action_response = Trends().run(
                Filter(
                    data={
                        "events": [
                            {
                                "id": "$pageview",
                                "name": "$pageview",
                                "type": "events",
                                "order": 0,
                            }
                        ],
                        **extra,
                    }
                ),
                self.team,
            )
        return action_response

    def test_with_breakdown_loads_two_unqiue_pages_of_values(self):
        response = self._run({"breakdown": "wildcard_route", "breakdown_type": "event"})

        assert len(response) == 26
        page_labels = [r["label"] for r in response if r["label"] != BREAKDOWN_OTHER_DISPLAY]
        assert len(page_labels) == 25
        assert sorted(page_labels), sorted(set(page_labels))  # all values are unique

        second_page_response = self._run({"breakdown": "wildcard_route", "breakdown_type": "event", "offset": 25})
        second_page_labels = [r["label"] for r in second_page_response if r["label"] != BREAKDOWN_OTHER_DISPLAY]

        assert len(page_labels) == len(second_page_labels)  # should be two pages of different results

        assert sorted(second_page_labels) == sorted(set(second_page_labels))  # all values are unique

        # no values from page one should be in page two
        assert [value for value in second_page_labels if value in page_labels] == []

        all_pages_response = self._run(
            {"breakdown": "wildcard_route", "breakdown_type": "event", "offset": 0, "breakdown_limit": 50}
        )
        all_pages_labels = [r["label"] for r in all_pages_response]

        assert len(all_pages_labels) == 50
        assert set(all_pages_labels) == set(page_labels + second_page_labels)

    def test_without_breakdown(self):
        response = self._run({})

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["label"], "$pageview")

        self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 50.0, 0.0, 0.0])
        self.assertEqual(response[0]["count"], 50.0)

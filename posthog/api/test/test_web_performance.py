import datetime
import json

from rest_framework import status

from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events


class TestWebPerformance(APIBaseTest):
    maxDiff = None

    # test multiple page views
    # test not all types present
    # test _no_ performance entries present
    def test_something(self) -> None:
        event_id = _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some-random-uid",
            timestamp=datetime.datetime(2012, 4, 1, 13, 45),
            properties={
                "$session_id": "12345",
                "$window_id": "67890",
                # truncated values to fit in the test
                "$performance_raw": json.dumps(
                    {
                        "navigation": [
                            ["name", "entryType", "duration",],
                            [["https://app.posthog.com/persons", "navigation", 1628.3,]],
                        ],
                        "paint": [["name", "entryType", "startTime"], [["first-paint", "paint", 3155.7],]],
                        "resource": [
                            ["name", "startTime", "duration",],
                            [
                                [
                                    "https://app.posthog.com/api/person/?distinct_id=FAED5BE9-D446-4A70-9176-AA22AA569C23",
                                    16382887.5,
                                    121.3,
                                ]
                            ],
                        ],
                    }
                ),
            },
        )
        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/web_performance/for_session/12345")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_response = response.json()
        self.assertEqual(
            actual_response,
            {
                "keys": {
                    "navigation": ["name", "entryType", "duration"],
                    "paint": ["name", "entryType", "startTime"],
                    "resource": ["name", "startTime", "duration"],
                },
                "results": [
                    {
                        "playerPosition": {"time": 1333287900000, "windowId": "67890"},
                        "type": "navigation",
                        "url": "https://app.posthog.com/persons",
                        "duration": 1628.3,
                        "eventId": event_id,
                        "eventName": None,
                        "timing": None,
                        "raw": ["https://app.posthog.com/persons", "navigation", 1628.3],
                    },
                    {
                        "playerPosition": {"time": 1333287903155.7, "windowId": "67890"},
                        "type": "paint",
                        "url": None,
                        "duration": None,
                        "eventId": None,
                        "eventName": "first-paint",
                        "timing": 3155.7,
                        "raw": ["first-paint", "paint", 3155.7],
                    },
                    {
                        "playerPosition": {"time": 1333304282887.5, "windowId": "67890"},
                        "type": "resource",
                        "eventId": None,
                        "eventName": None,
                        "timing": None,
                        "url": "https://app.posthog.com/api/person/?distinct_id=FAED5BE9-D446-4A70-9176-AA22AA569C23",
                        "duration": 121.3,
                        "raw": [
                            "https://app.posthog.com/api/person/?distinct_id=FAED5BE9-D446-4A70-9176-AA22AA569C23",
                            16382887.5,
                            121.3,
                        ],
                    },
                ],
            },
        )

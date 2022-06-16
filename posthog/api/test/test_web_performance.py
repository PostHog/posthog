import datetime
import json
from typing import Dict, List

from rest_framework import status

from posthog.models import Team
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events


def navigation_entry(url: str, duration: float) -> List:
    return [
        ["name", "entryType", "duration"],
        [[url, "navigation", duration]],
    ]


def paint_entry(start_time: float) -> List:
    return [["name", "entryType", "startTime"], [["first-paint", "paint", start_time]]]


def resource_entry(start_time: float, duration: float) -> List:
    return [
        ["name", "startTime", "duration"],
        [
            [
                "https://app.posthog.com/api/person/?distinct_id=FAED5BE9-D446-4A70-9176-AA22AA569C23",
                start_time,
                duration,
            ]
        ],
    ]


def create_event(team: Team, timestamp: datetime.datetime, session_id: str, performance_raw: Dict) -> str:
    return _create_event(
        event="$pageview",
        team=team,
        distinct_id="some-random-uid",
        timestamp=timestamp,
        properties={
            "$session_id": session_id,
            "$window_id": "67890",
            # truncated values to fit in the test
            "$performance_raw": json.dumps(performance_raw),
        },
    )


def pageview_response(event_id: str, url: str, player_time: float, duration: float) -> Dict:
    return {
        "playerPosition": {"time": player_time, "windowId": "67890"},
        "type": "navigation",
        "url": url,
        "duration": duration,
        "eventId": event_id,
        "eventName": None,
        "timing": None,
        "raw": [url, "navigation", duration],
    }


def paint_response(player_time: float, timing: float) -> Dict:
    return {
        "playerPosition": {"time": player_time, "windowId": "67890"},
        "type": "paint",
        "url": None,
        "duration": None,
        "eventId": None,
        "eventName": "first-paint",
        "timing": timing,
        "raw": ["first-paint", "paint", timing],
    }


def resource_response(player_time: float, raw_time: float, duration: float) -> Dict:
    return {
        "playerPosition": {"time": player_time, "windowId": "67890"},
        "type": "resource",
        "eventId": None,
        "eventName": None,
        "timing": None,
        "url": "https://app.posthog.com/api/person/?distinct_id=FAED5BE9-D446-4A70-9176-AA22AA569C23",
        "duration": duration,
        "raw": [
            "https://app.posthog.com/api/person/?distinct_id=FAED5BE9-D446-4A70-9176-AA22AA569C23",
            raw_time,
            duration,
        ],
    }


class TestWebPerformance(APIBaseTest):
    maxDiff = None

    def test_empty_performance_raw(self) -> None:
        session_id = "1"
        create_event(
            team=self.team, timestamp=datetime.datetime(2012, 4, 1, 13, 45), session_id=session_id, performance_raw={},
        )
        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/web_performance/for_session/{session_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_response = response.json()

        self.assertEqual(
            actual_response, {"keys": {}, "results": [],},
        )

    def test_only_paint_in_performance_raw(self) -> None:
        session_id = "2"
        create_event(
            team=self.team,
            timestamp=datetime.datetime(2012, 4, 1, 13, 45),
            session_id=session_id,
            performance_raw={"paint": paint_entry(start_time=3155.7),},
        )
        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/web_performance/for_session/{session_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_response = response.json()

        self.assertEqual(actual_response["keys"], {"paint": ["name", "entryType", "startTime"],})
        self.assertEqual(actual_response["results"], [paint_response(player_time=1333287903155.7, timing=3155.7)])

    def test_only_resource_in_performance_raw(self) -> None:
        session_id = "3"
        create_event(
            team=self.team,
            timestamp=datetime.datetime(2012, 4, 1, 13, 45),
            session_id=session_id,
            performance_raw={"resource": resource_entry(start_time=2000, duration=121.3),},
        )
        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/web_performance/for_session/{session_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_response = response.json()

        self.assertEqual(actual_response["keys"], {"resource": ["name", "startTime", "duration"]})
        self.assertEqual(
            actual_response["results"], [resource_response(player_time=1333287902000, duration=121.3, raw_time=2000)],
        )

    def test_only_navigation_in_performance_raw(self) -> None:
        session_id = "4"
        event_id = create_event(
            team=self.team,
            timestamp=datetime.datetime(2012, 4, 1, 13, 45),
            session_id=session_id,
            performance_raw={"navigation": navigation_entry(url="https://app.posthog.com/persons", duration=1628.3),},
        )
        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/web_performance/for_session/{session_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_response = response.json()

        self.assertEqual(actual_response["keys"], {"navigation": ["name", "entryType", "duration"]})
        self.assertEqual(
            actual_response["results"],
            [
                pageview_response(
                    event_id=event_id,
                    url="https://app.posthog.com/persons",
                    player_time=1333287900000,
                    duration=1628.3,
                )
            ],
        )

    def test_two_page_views_in_a_session(self) -> None:
        session_id = "123456"
        event_id_one = create_event(
            team=self.team,
            timestamp=datetime.datetime(2012, 4, 1, 13, 45),
            session_id=session_id,
            performance_raw={
                "navigation": navigation_entry(url="https://app.posthog.com/persons", duration=1628.3),
                "resource": resource_entry(start_time=2000, duration=121.3),
            },
        )
        event_id_two = create_event(
            team=self.team,
            timestamp=datetime.datetime(2012, 4, 1, 13, 50),
            session_id=session_id,
            performance_raw={
                "navigation": navigation_entry(url="https://app.posthog.com/persons/second_page", duration=1628.3),
                "paint": paint_entry(start_time=2000),
                "resource": resource_entry(start_time=2500, duration=121.3),
            },
        )

        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/web_performance/for_session/{session_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_response = response.json()

        self.assertEqual(
            actual_response["keys"],
            {
                "navigation": ["name", "entryType", "duration"],
                "paint": ["name", "entryType", "startTime"],
                "resource": ["name", "startTime", "duration"],
            },
        )

        expected_results = [
            pageview_response(
                event_id=event_id_one, url="https://app.posthog.com/persons", player_time=1333287900000, duration=1628.3
            ),
            resource_response(player_time=1333287902000, duration=121.3, raw_time=2000),
            pageview_response(
                event_id=event_id_two,
                url="https://app.posthog.com/persons/second_page",
                player_time=1333288200000,
                duration=1628.3,
            ),
            paint_response(player_time=1333288202000, timing=2000),
            resource_response(player_time=1333288202500, duration=121.3, raw_time=2500),
        ]

        for index, actual_result in enumerate(actual_response["results"]):
            self.assertEqual(actual_result, expected_results[index], f"index: {index}")

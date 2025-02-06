from rest_framework import status
from freezegun import freeze_time

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from posthog.models.utils import uuid7


class TestWebVitalsAPI(ClickhouseTestMixin, APIBaseTest):
    def test_web_vitals_no_data(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/web_vitals/?pathname=/test-path")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"error": "No web vitals data found for this path"})

    def test_web_vitals_missing_pathname(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/web_vitals/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "attr": "pathname",
                "code": "invalid_input",
                "detail": "This field is required.",
            },
        )

    def test_web_vitals_with_data(self):
        # Freeze time at query time
        with freeze_time("2024-01-07T12:00:00.000Z"):
            session_id = str(uuid7("2024-01-07"))

            # Create events across the last 7 days
            for day in range(7):
                timestamp = f"2024-01-{str(day+1).zfill(2)}T12:00:00.000Z"

                # Create INP events, P90 should be 300
                _create_event(
                    team=self.team,
                    event="$web_vitals",
                    distinct_id="test_user",
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": "/test-path",
                        "$web_vitals_INP_value": 50 + (day * 50),
                    },
                )

                # Create LCP events, P90 should be 3500
                _create_event(
                    team=self.team,
                    event="$web_vitals",
                    distinct_id="test_user",
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": "/test-path",
                        "$web_vitals_LCP_value": 1000 + (day * 500),
                    },
                )

                # Create CLS events, P90 should be 0.6
                _create_event(
                    team=self.team,
                    event="$web_vitals",
                    distinct_id="test_user",
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": "/test-path",
                        "$web_vitals_CLS_value": 0.1 + (day * 0.1),
                    },
                )

                # Create FCP events, P90 should be 2000
                _create_event(
                    team=self.team,
                    event="$web_vitals",
                    distinct_id="test_user",
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": "/test-path",
                        "$web_vitals_FCP_value": 500 + (day * 300),
                    },
                )

            # Create events for a different path that should not affect results
            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="test_user",
                timestamp="2024-01-07T12:00:00.000Z",
                properties={
                    "$session_id": session_id,
                    "$pathname": "/other-path",
                    "$web_vitals_INP_value": 9999,
                },
            )
            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="test_user",
                timestamp="2024-01-07T12:00:00.000Z",
                properties={
                    "$session_id": session_id,
                    "$pathname": "/other-path",
                    "$web_vitals_LCP_value": 9999,
                },
            )
            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="test_user",
                timestamp="2024-01-07T12:00:00.000Z",
                properties={
                    "$session_id": session_id,
                    "$pathname": "/other-path",
                    "$web_vitals_CLS_value": 9.9,
                },
            )

            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="test_user",
                timestamp="2024-01-07T12:00:00.000Z",
                properties={
                    "$session_id": session_id,
                    "$pathname": "/other-path",
                    "$web_vitals_FCP_value": 9999,
                },
            )

            # Flush the events to ClickHouse
            flush_persons_and_events()

            response = self.client.get(f"/api/environments/{self.team.pk}/web_vitals/?pathname=/test-path")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            data = response.json()
            self.assertIn("result", data)
            self.assertTrue(len(data["result"]) > 0)

            # Verify that all web vitals metrics are present in the response
            metrics = [series["name"] for series in data["result"]]
            self.assertCountEqual(metrics, ["INP", "LCP", "CLS", "FCP"])

            # Verify the p90 values of the metrics
            for series in data["result"]:
                if series["name"] == "INP":
                    self.assertEqual(series["data"][-1], 300)  # p90 of values 50,100,150,200,250,300,350
                elif series["name"] == "LCP":
                    self.assertEqual(series["data"][-1], 3500)  # p90 of values 1000,1500,2000,2500,3000,3500,4000
                elif series["name"] == "CLS":
                    self.assertEqual(series["data"][-1], 0.6)  # p90 of values 0.1,0.2,0.3,0.4,0.5,0.6,0.7
                elif series["name"] == "FCP":
                    self.assertEqual(series["data"][-1], 2000)  # p90 of values 500,800,1100,1400,1700,2000,2300

from .base import BaseTest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time
from unittest.mock import patch, call
from datetime import timedelta
from urllib.parse import quote
import base64
import json
import gzip


class TestCapture(BaseTest):
    TESTS_API = True

    def _dict_to_json(self, data: dict) -> str:
        return json.dumps(data)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _dict_from_b64(self, data: str) -> dict:
        return json.loads(base64.b64decode(data))

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_capture_event(self, patch_process_event):
        data = {
            "event": "$autocapture",
            "properties": {
                "distinct_id": 2,
                "token": self.team.api_token,
                "$elements": [
                    {
                        "tag_name": "a",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "attr__class": "btn btn-sm",
                    },
                    {
                        "tag_name": "div",
                        "nth_child": 1,
                        "nth_of_type": 2,
                        "$el_text": "💻",
                    },
                ],
            },
        }
        now = timezone.now()
        with freeze_time(now):
            with self.assertNumQueries(1):
                response = self.client.get(
                    "/e/?data=%s" % quote(self._dict_to_json(data)),
                    content_type="application/json",
                    HTTP_ORIGIN="https://localhost",
                )
        self.assertEqual(
            response.get("access-control-allow-origin"), "https://localhost"
        )
        arguments = patch_process_event.call_args[1]
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": data,
                "team_id": self.team.pk,
            },
        )

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_multiple_events(self, patch_process_event):
        self.client.post(
            "/track/",
            data={
                "data": json.dumps(
                    [
                        {
                            "event": "beep",
                            "properties": {
                                "distinct_id": "eeee",
                                "token": self.team.api_token,
                            },
                        },
                        {
                            "event": "boop",
                            "properties": {
                                "distinct_id": "aaaa",
                                "token": self.team.api_token,
                            },
                        },
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )
        self.assertEqual(patch_process_event.call_count, 2)

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_emojis_in_text(self, patch_process_event):
        self.team.api_token = "xp9qT2VLY76JJg"
        self.team.save()
        self.client.post(
            "/track/",
            data={
                "data": "eyJldmVudCI6ICIkd2ViX2V2ZW50IiwicHJvcGVydGllcyI6IHsiJG9zIjogIk1hYyBPUyBYIiwiJGJyb3dzZXIiOiAiQ2hyb21lIiwiJHJlZmVycmVyIjogImh0dHBzOi8vYXBwLmhpYmVybHkuY29tL2xvZ2luP25leHQ9LyIsIiRyZWZlcnJpbmdfZG9tYWluIjogImFwcC5oaWJlcmx5LmNvbSIsIiRjdXJyZW50X3VybCI6ICJodHRwczovL2FwcC5oaWJlcmx5LmNvbS8iLCIkYnJvd3Nlcl92ZXJzaW9uIjogNzksIiRzY3JlZW5faGVpZ2h0IjogMjE2MCwiJHNjcmVlbl93aWR0aCI6IDM4NDAsInBoX2xpYiI6ICJ3ZWIiLCIkbGliX3ZlcnNpb24iOiAiMi4zMy4xIiwiJGluc2VydF9pZCI6ICJnNGFoZXFtejVrY3AwZ2QyIiwidGltZSI6IDE1ODA0MTAzNjguMjY1LCJkaXN0aW5jdF9pZCI6IDYzLCIkZGV2aWNlX2lkIjogIjE2ZmQ1MmRkMDQ1NTMyLTA1YmNhOTRkOWI3OWFiLTM5NjM3YzBlLTFhZWFhMC0xNmZkNTJkZDA0NjQxZCIsIiRpbml0aWFsX3JlZmVycmVyIjogIiRkaXJlY3QiLCIkaW5pdGlhbF9yZWZlcnJpbmdfZG9tYWluIjogIiRkaXJlY3QiLCIkdXNlcl9pZCI6IDYzLCIkZXZlbnRfdHlwZSI6ICJjbGljayIsIiRjZV92ZXJzaW9uIjogMSwiJGhvc3QiOiAiYXBwLmhpYmVybHkuY29tIiwiJHBhdGhuYW1lIjogIi8iLCIkZWxlbWVudHMiOiBbCiAgICB7InRhZ19uYW1lIjogImJ1dHRvbiIsIiRlbF90ZXh0IjogIu2gve2yuyBXcml0aW5nIGNvZGUiLCJjbGFzc2VzIjogWwogICAgImJ0biIsCiAgICAiYnRuLXNlY29uZGFyeSIKXSwiYXR0cl9fY2xhc3MiOiAiYnRuIGJ0bi1zZWNvbmRhcnkiLCJhdHRyX19zdHlsZSI6ICJjdXJzb3I6IHBvaW50ZXI7IG1hcmdpbi1yaWdodDogOHB4OyBtYXJnaW4tYm90dG9tOiAxcmVtOyIsIm50aF9jaGlsZCI6IDIsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiZmVlZGJhY2stc3RlcCIsCiAgICAiZmVlZGJhY2stc3RlcC1zZWxlY3RlZCIKXSwiYXR0cl9fY2xhc3MiOiAiZmVlZGJhY2stc3RlcCBmZWVkYmFjay1zdGVwLXNlbGVjdGVkIiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJnaXZlLWZlZWRiYWNrIgpdLCJhdHRyX19jbGFzcyI6ICJnaXZlLWZlZWRiYWNrIiwiYXR0cl9fc3R5bGUiOiAid2lkdGg6IDkwJTsgbWFyZ2luOiAwcHggYXV0bzsgZm9udC1zaXplOiAxNXB4OyBwb3NpdGlvbjogcmVsYXRpdmU7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9fc3R5bGUiOiAib3ZlcmZsb3c6IGhpZGRlbjsiLCJudGhfY2hpbGQiOiAxLCJudGhfb2ZfdHlwZSI6IDF9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgIm1vZGFsLWJvZHkiCl0sImF0dHJfX2NsYXNzIjogIm1vZGFsLWJvZHkiLCJhdHRyX19zdHlsZSI6ICJmb250LXNpemU6IDE1cHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1jb250ZW50IgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1jb250ZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1kaWFsb2ciLAogICAgIm1vZGFsLWxnIgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1kaWFsb2cgbW9kYWwtbGciLCJhdHRyX19yb2xlIjogImRvY3VtZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbCIsCiAgICAiZmFkZSIsCiAgICAic2hvdyIKXSwiYXR0cl9fY2xhc3MiOiAibW9kYWwgZmFkZSBzaG93IiwiYXR0cl9fc3R5bGUiOiAiZGlzcGxheTogYmxvY2s7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJrLXBvcnRsZXRfX2JvZHkiLAogICAgIiIKXSwiYXR0cl9fY2xhc3MiOiAiay1wb3J0bGV0X19ib2R5ICIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDBweDsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgImstcG9ydGxldCIsCiAgICAiay1wb3J0bGV0LS1oZWlnaHQtZmx1aWQiCl0sImF0dHJfX2NsYXNzIjogImstcG9ydGxldCBrLXBvcnRsZXQtLWhlaWdodC1mbHVpZCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiY29sLWxnLTYiCl0sImF0dHJfX2NsYXNzIjogImNvbC1sZy02IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJyb3ciCl0sImF0dHJfX2NsYXNzIjogInJvdyIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDQwcHggMzBweCAwcHg7IGJhY2tncm91bmQtY29sb3I6IHJnYigyMzksIDIzOSwgMjQ1KTsgbWFyZ2luLXRvcDogLTQwcHg7IG1pbi1oZWlnaHQ6IGNhbGMoMTAwdmggLSA0MHB4KTsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJhdHRyX19zdHlsZSI6ICJtYXJnaW4tdG9wOiAwcHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJBcHAiCl0sImF0dHJfX2NsYXNzIjogIkFwcCIsImF0dHJfX3N0eWxlIjogImNvbG9yOiByZ2IoNTIsIDYxLCA2Mik7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9faWQiOiAicm9vdCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImJvZHkiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDF9Cl0sInRva2VuIjogInhwOXFUMlZMWTc2SkpnIn19"
            },
        )

        self.assertEqual(
            patch_process_event.call_args[1]["data"]["properties"]["$elements"][0][
                "$el_text"
            ],
            "💻 Writing code",
        )

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_incorrect_padding(self, patch_process_event):
        response = self.client.get(
            "/e/?data=eyJldmVudCI6IndoYXRldmVmciIsInByb3BlcnRpZXMiOnsidG9rZW4iOiJ0b2tlbjEyMyIsImRpc3RpbmN0X2lkIjoiYXNkZiJ9fQ",
            content_type="application/json",
            HTTP_REFERER="https://localhost",
        )
        self.assertEqual(response.json()["status"], 1)
        self.assertEqual(patch_process_event.call_args[1]["data"]["event"], "whatevefr")

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_ignore_empty_request(self, patch_process_event):
        response = self.client.get(
            "/e/?data=",
            content_type="application/json",
            HTTP_ORIGIN="https://localhost",
        )
        self.assertEqual(response.content, b"1")
        self.assertEqual(patch_process_event.call_count, 0)

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_batch(self, patch_process_event):
        data = {"type": "capture", "event": "user signed up", "distinct_id": "2"}
        response = self.client.post(
            "/batch/",
            data={"api_key": self.team.api_token, "batch": [data]},
            content_type="application/json",
        )
        arguments = patch_process_event.call_args[1]
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": data,
                "team_id": self.team.pk,
            },
        )

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_batch_gzip(self, patch_process_event):
        data = {
            "api_key": self.team.api_token,
            "batch": [
                {"type": "capture", "event": "user signed up", "distinct_id": "2"}
            ],
        }

        response = self.client.generic(
            "POST",
            "/batch/",
            data=gzip.compress(json.dumps(data).encode()),
            content_type="application/json",
            HTTP_CONTENT_ENCODING="gzip",
        )

        arguments = patch_process_event.call_args[1]
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": data["batch"][0],
                "team_id": self.team.pk,
            },
        )

    def test_batch_incorrect_token(self):
        response = self.client.post(
            "/batch/",
            data={
                "api_key": "this-token-doesnt-exist",
                "batch": [
                    {
                        "type": "capture",
                        "event": "user signed up",
                        "distinct_id": "whatever",
                    },
                ],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["message"],
            "API key is incorrect. You can find your API key in the /setup page in PostHog.",
        )

    def test_batch_token_not_set(self):
        response = self.client.post(
            "/batch/",
            data={
                "batch": [
                    {
                        "type": "capture",
                        "event": "user signed up",
                        "distinct_id": "whatever",
                    },
                ]
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["message"],
            "No api_key set. You can find your API key in the /setup page in posthog",
        )

    def test_batch_distinct_id_not_set(self):
        response = self.client.post(
            "/batch/",
            data={
                "api_key": self.team.api_token,
                "batch": [{"type": "capture", "event": "user signed up",},],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "You need to set a distinct_id.")

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_engage(self, patch_process_event):
        response = self.client.get(
            "/engage/?data=%s"
            % quote(
                self._dict_to_json(
                    {
                        "$set": {"$os": "Mac OS X",},
                        "$token": "token123",
                        "$distinct_id": 3,
                        "$device_id": "16fd4afae9b2d8-0fce8fe900d42b-39637c0e-7e9000-16fd4afae9c395",
                        "$user_id": 3,
                    }
                )
            ),
            content_type="application/json",
            HTTP_ORIGIN="https://localhost",
        )
        arguments = patch_process_event.call_args[1]
        self.assertEqual(arguments["data"]["event"], "$identify")
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        arguments.pop("data")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "distinct_id": "3",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "team_id": self.team.pk,
            },
        )

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_python_library(self, patch_process_event):
        self.client.post(
            "/track/",
            data={
                "data": self._dict_to_b64(
                    {"event": "$pageview", "properties": {"distinct_id": "eeee",},}
                ),
                "api_key": self.team.api_token,  # main difference in this test
            },
        )
        arguments = patch_process_event.call_args[1]
        self.assertEqual(arguments["team_id"], self.team.pk)

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_base64_decode_variations(self, patch_process_event):
        base64 = "eyJldmVudCI6IiRwYWdldmlldyIsInByb3BlcnRpZXMiOnsiZGlzdGluY3RfaWQiOiJlZWVlZWVlZ8+lZWVlZWUifX0="
        dict = self._dict_from_b64(base64)
        self.assertDictEqual(
            dict,
            {"event": "$pageview", "properties": {"distinct_id": "eeeeeeegϥeeeee",},},
        )

        # POST with "+" in the base64
        self.client.post(
            "/track/",
            data={
                "data": base64,
                "api_key": self.team.api_token,  # main difference in this test
            },
        )
        arguments = patch_process_event.call_args[1]
        self.assertEqual(arguments["team_id"], self.team.pk)
        self.assertEqual(arguments["distinct_id"], "eeeeeeegϥeeeee")

        # POST with " " in the base64 instead of the "+"
        self.client.post(
            "/track/",
            data={
                "data": base64.replace("+", " "),
                "api_key": self.team.api_token,  # main difference in this test
            },
        )
        arguments = patch_process_event.call_args[1]
        self.assertEqual(arguments["team_id"], self.team.pk)
        self.assertEqual(arguments["distinct_id"], "eeeeeeegϥeeeee")

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_js_library_underscore_sent_at(self, patch_process_event):
        now = timezone.now()
        tomorrow = now + timedelta(days=1, hours=2)
        tomorrow_sent_at = now + timedelta(days=1, hours=2, minutes=10)

        data = {
            "event": "movie played",
            "timestamp": tomorrow.isoformat(),
            "properties": {"distinct_id": 2, "token": self.team.api_token},
        }

        self.client.get(
            "/e/?_=%s&data=%s"
            % (int(tomorrow_sent_at.timestamp()), quote(self._dict_to_json(data))),
            content_type="application/json",
            HTTP_ORIGIN="https://localhost",
        )

        arguments = patch_process_event.call_args[1]
        arguments.pop("now")  # can't compare fakedate

        # right time sent as sent_at to process_event

        self.assertEqual(arguments["sent_at"].tzinfo, timezone.utc)

        timediff = arguments["sent_at"].timestamp() - tomorrow_sent_at.timestamp()
        self.assertLess(abs(timediff), 1)
        self.assertEqual(arguments["data"]["timestamp"], tomorrow.isoformat())

    @patch("posthog.models.team.TEAM_CACHE", {})
    @patch("posthog.tasks.process_event.process_event.delay")
    def test_sent_at_field(self, patch_process_event):
        now = timezone.now()
        tomorrow = now + timedelta(days=1, hours=2)
        tomorrow_sent_at = now + timedelta(days=1, hours=2, minutes=10)

        self.client.post(
            "/track/",
            data={
                "sent_at": tomorrow_sent_at.isoformat(),
                "data": self._dict_to_b64(
                    {
                        "event": "$pageview",
                        "timestamp": tomorrow.isoformat(),
                        "properties": {"distinct_id": "eeee",},
                    }
                ),
                "api_key": self.team.api_token,  # main difference in this test
            },
        )

        arguments = patch_process_event.call_args[1]
        arguments.pop("now")  # can't compare fakedate

        # right time sent as sent_at to process_event
        timediff = arguments["sent_at"].timestamp() - tomorrow_sent_at.timestamp()
        self.assertLess(abs(timediff), 1)
        self.assertEqual(arguments["data"]["timestamp"], tomorrow.isoformat())

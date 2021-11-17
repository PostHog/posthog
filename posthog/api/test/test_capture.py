import base64
import gzip
import json
from datetime import timedelta
from typing import Any, Dict, List, Union
from unittest.mock import MagicMock, call, patch
from urllib.parse import quote

import lzstring
from django.test.client import Client
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from posthog.api.test.mock_sentry import mock_sentry_context_for_tagging
from posthog.models import Person, PersonalAPIKey
from posthog.models.feature_flag import FeatureFlag, FeatureFlagOverride
from posthog.test.base import BaseTest


def mocked_get_team_from_token(_: Any) -> None:
    raise Exception("test exception")


class TestCapture(BaseTest):
    """
    Tests all data capture endpoints (e.g. `/capture` `/track`).
    We use Django's base test class instead of DRF's because we need granular control over the Content-Type sent over.
    """

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.client = Client()

    def _to_json(self, data: Union[Dict, List]) -> str:
        return json.dumps(data)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _dict_from_b64(self, data: str) -> dict:
        return json.loads(base64.b64decode(data))

    def _to_arguments(self, patch_process_event_with_plugins: Any) -> dict:
        args = patch_process_event_with_plugins.call_args[1]["args"]
        distinct_id, ip, site_url, data, team_id, now, sent_at = args

        return {
            "distinct_id": distinct_id,
            "ip": ip,
            "site_url": site_url,
            "data": data,
            "team_id": team_id,
            "now": now,
            "sent_at": sent_at,
        }

    @patch("posthog.api.capture.celery_app.send_task")
    def test_capture_event(self, patch_process_event_with_plugins):
        data = {
            "event": "$autocapture",
            "properties": {
                "distinct_id": 2,
                "token": self.team.api_token,
                "$elements": [
                    {"tag_name": "a", "nth_child": 1, "nth_of_type": 2, "attr__class": "btn btn-sm",},
                    {"tag_name": "div", "nth_child": 1, "nth_of_type": 2, "$el_text": "💻",},
                ],
            },
        }
        now = timezone.now()
        with freeze_time(now):
            with self.assertNumQueries(1):
                response = self.client.get("/e/?data=%s" % quote(self._to_json(data)), HTTP_ORIGIN="https://localhost",)
        self.assertEqual(response.get("access-control-allow-origin"), "https://localhost")
        arguments = self._to_arguments(patch_process_event_with_plugins)
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

    @patch("posthog.api.capture.configure_scope")
    @patch("posthog.api.capture.celery_app.send_task", MagicMock())
    def test_capture_event_adds_library_to_sentry(self, patched_scope):
        mock_set_tag = mock_sentry_context_for_tagging(patched_scope)

        data = {
            "event": "$autocapture",
            "properties": {
                "$lib": "web",
                "$lib_version": "1.14.1",
                "distinct_id": 2,
                "token": self.team.api_token,
                "$elements": [
                    {"tag_name": "a", "nth_child": 1, "nth_of_type": 2, "attr__class": "btn btn-sm",},
                    {"tag_name": "div", "nth_child": 1, "nth_of_type": 2, "$el_text": "💻",},
                ],
            },
        }
        with freeze_time(timezone.now()):
            self.client.get(
                "/e/?data=%s" % quote(self._to_json(data)), HTTP_ORIGIN="https://localhost",
            )

        mock_set_tag.assert_has_calls([call("library", "web"), call("library.version", "1.14.1")])

    @patch("posthog.api.capture.configure_scope")
    @patch("posthog.api.capture.celery_app.send_task", MagicMock())
    def test_capture_event_adds_unknown_to_sentry_when_no_properties_sent(self, patched_scope):
        mock_set_tag = mock_sentry_context_for_tagging(patched_scope)

        data = {
            "event": "$autocapture",
            "properties": {
                "distinct_id": 2,
                "token": self.team.api_token,
                "$elements": [
                    {"tag_name": "a", "nth_child": 1, "nth_of_type": 2, "attr__class": "btn btn-sm",},
                    {"tag_name": "div", "nth_child": 1, "nth_of_type": 2, "$el_text": "💻",},
                ],
            },
        }
        with freeze_time(timezone.now()):
            self.client.get(
                "/e/?data=%s" % quote(self._to_json(data)), HTTP_ORIGIN="https://localhost",
            )

        mock_set_tag.assert_has_calls([call("library", "unknown"), call("library.version", "unknown")])

    @patch("posthog.api.capture.celery_app.send_task")
    def test_personal_api_key(self, patch_process_event_with_plugins):
        key = PersonalAPIKey(label="X", user=self.user)
        key.save()
        data = {
            "event": "$autocapture",
            "api_key": key.value,
            "project_id": self.team.id,
            "properties": {
                "distinct_id": 2,
                "$elements": [
                    {"tag_name": "a", "nth_child": 1, "nth_of_type": 2, "attr__class": "btn btn-sm",},
                    {"tag_name": "div", "nth_child": 1, "nth_of_type": 2, "$el_text": "💻",},
                ],
            },
        }
        now = timezone.now()
        with freeze_time(now):
            with self.assertNumQueries(4):
                response = self.client.get("/e/?data=%s" % quote(self._to_json(data)), HTTP_ORIGIN="https://localhost",)
        self.assertEqual(response.get("access-control-allow-origin"), "https://localhost")
        arguments = self._to_arguments(patch_process_event_with_plugins)
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

    @patch("posthog.api.capture.celery_app.send_task")
    def test_personal_api_key_from_batch_request(self, patch_process_event_with_plugins):
        # Originally issue POSTHOG-2P8
        key = PersonalAPIKey(label="X", user=self.user)
        key.save()
        data = [
            {
                "event": "$pageleave",
                "api_key": key.value,
                "project_id": self.team.id,
                "properties": {
                    "$os": "Linux",
                    "$browser": "Chrome",
                    "$device_type": "Desktop",
                    "distinct_id": "94b03e599131fd5026b",
                    "token": "fake token",  # as this is invalid, will do API key authentication
                },
                "timestamp": "2021-04-20T19:11:33.841Z",
            }
        ]
        response = self.client.get("/e/?data=%s" % quote(self._to_json(data)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        arguments = self._to_arguments(patch_process_event_with_plugins)
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "distinct_id": "94b03e599131fd5026b",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": {
                    "event": "$pageleave",
                    "api_key": key.value,
                    "project_id": self.team.id,
                    "properties": {
                        "$os": "Linux",
                        "$browser": "Chrome",
                        "$device_type": "Desktop",
                        "distinct_id": "94b03e599131fd5026b",
                        "token": "fake token",
                    },
                    "timestamp": "2021-04-20T19:11:33.841Z",
                },
                "team_id": self.team.id,
            },
        )

    @patch("posthog.api.capture.celery_app.send_task")
    def test_multiple_events(self, patch_process_event_with_plugins):
        self.client.post(
            "/track/",
            data={
                "data": json.dumps(
                    [
                        {"event": "beep", "properties": {"distinct_id": "eeee", "token": self.team.api_token,},},
                        {"event": "boop", "properties": {"distinct_id": "aaaa", "token": self.team.api_token,},},
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )
        self.assertEqual(patch_process_event_with_plugins.call_count, 2)

    @patch("posthog.api.capture.celery_app.send_task")
    def test_emojis_in_text(self, patch_process_event_with_plugins):
        self.team.api_token = "xp9qT2VLY76JJg"
        self.team.save()

        # Make sure the endpoint works with and without the trailing slash
        self.client.post(
            "/track",
            data={
                "data": "eyJldmVudCI6ICIkd2ViX2V2ZW50IiwicHJvcGVydGllcyI6IHsiJG9zIjogIk1hYyBPUyBYIiwiJGJyb3dzZXIiOiAiQ2hyb21lIiwiJHJlZmVycmVyIjogImh0dHBzOi8vYXBwLmhpYmVybHkuY29tL2xvZ2luP25leHQ9LyIsIiRyZWZlcnJpbmdfZG9tYWluIjogImFwcC5oaWJlcmx5LmNvbSIsIiRjdXJyZW50X3VybCI6ICJodHRwczovL2FwcC5oaWJlcmx5LmNvbS8iLCIkYnJvd3Nlcl92ZXJzaW9uIjogNzksIiRzY3JlZW5faGVpZ2h0IjogMjE2MCwiJHNjcmVlbl93aWR0aCI6IDM4NDAsInBoX2xpYiI6ICJ3ZWIiLCIkbGliX3ZlcnNpb24iOiAiMi4zMy4xIiwiJGluc2VydF9pZCI6ICJnNGFoZXFtejVrY3AwZ2QyIiwidGltZSI6IDE1ODA0MTAzNjguMjY1LCJkaXN0aW5jdF9pZCI6IDYzLCIkZGV2aWNlX2lkIjogIjE2ZmQ1MmRkMDQ1NTMyLTA1YmNhOTRkOWI3OWFiLTM5NjM3YzBlLTFhZWFhMC0xNmZkNTJkZDA0NjQxZCIsIiRpbml0aWFsX3JlZmVycmVyIjogIiRkaXJlY3QiLCIkaW5pdGlhbF9yZWZlcnJpbmdfZG9tYWluIjogIiRkaXJlY3QiLCIkdXNlcl9pZCI6IDYzLCIkZXZlbnRfdHlwZSI6ICJjbGljayIsIiRjZV92ZXJzaW9uIjogMSwiJGhvc3QiOiAiYXBwLmhpYmVybHkuY29tIiwiJHBhdGhuYW1lIjogIi8iLCIkZWxlbWVudHMiOiBbCiAgICB7InRhZ19uYW1lIjogImJ1dHRvbiIsIiRlbF90ZXh0IjogIu2gve2yuyBXcml0aW5nIGNvZGUiLCJjbGFzc2VzIjogWwogICAgImJ0biIsCiAgICAiYnRuLXNlY29uZGFyeSIKXSwiYXR0cl9fY2xhc3MiOiAiYnRuIGJ0bi1zZWNvbmRhcnkiLCJhdHRyX19zdHlsZSI6ICJjdXJzb3I6IHBvaW50ZXI7IG1hcmdpbi1yaWdodDogOHB4OyBtYXJnaW4tYm90dG9tOiAxcmVtOyIsIm50aF9jaGlsZCI6IDIsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiZmVlZGJhY2stc3RlcCIsCiAgICAiZmVlZGJhY2stc3RlcC1zZWxlY3RlZCIKXSwiYXR0cl9fY2xhc3MiOiAiZmVlZGJhY2stc3RlcCBmZWVkYmFjay1zdGVwLXNlbGVjdGVkIiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJnaXZlLWZlZWRiYWNrIgpdLCJhdHRyX19jbGFzcyI6ICJnaXZlLWZlZWRiYWNrIiwiYXR0cl9fc3R5bGUiOiAid2lkdGg6IDkwJTsgbWFyZ2luOiAwcHggYXV0bzsgZm9udC1zaXplOiAxNXB4OyBwb3NpdGlvbjogcmVsYXRpdmU7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9fc3R5bGUiOiAib3ZlcmZsb3c6IGhpZGRlbjsiLCJudGhfY2hpbGQiOiAxLCJudGhfb2ZfdHlwZSI6IDF9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgIm1vZGFsLWJvZHkiCl0sImF0dHJfX2NsYXNzIjogIm1vZGFsLWJvZHkiLCJhdHRyX19zdHlsZSI6ICJmb250LXNpemU6IDE1cHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1jb250ZW50IgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1jb250ZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1kaWFsb2ciLAogICAgIm1vZGFsLWxnIgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1kaWFsb2cgbW9kYWwtbGciLCJhdHRyX19yb2xlIjogImRvY3VtZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbCIsCiAgICAiZmFkZSIsCiAgICAic2hvdyIKXSwiYXR0cl9fY2xhc3MiOiAibW9kYWwgZmFkZSBzaG93IiwiYXR0cl9fc3R5bGUiOiAiZGlzcGxheTogYmxvY2s7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJrLXBvcnRsZXRfX2JvZHkiLAogICAgIiIKXSwiYXR0cl9fY2xhc3MiOiAiay1wb3J0bGV0X19ib2R5ICIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDBweDsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgImstcG9ydGxldCIsCiAgICAiay1wb3J0bGV0LS1oZWlnaHQtZmx1aWQiCl0sImF0dHJfX2NsYXNzIjogImstcG9ydGxldCBrLXBvcnRsZXQtLWhlaWdodC1mbHVpZCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiY29sLWxnLTYiCl0sImF0dHJfX2NsYXNzIjogImNvbC1sZy02IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJyb3ciCl0sImF0dHJfX2NsYXNzIjogInJvdyIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDQwcHggMzBweCAwcHg7IGJhY2tncm91bmQtY29sb3I6IHJnYigyMzksIDIzOSwgMjQ1KTsgbWFyZ2luLXRvcDogLTQwcHg7IG1pbi1oZWlnaHQ6IGNhbGMoMTAwdmggLSA0MHB4KTsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJhdHRyX19zdHlsZSI6ICJtYXJnaW4tdG9wOiAwcHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJBcHAiCl0sImF0dHJfX2NsYXNzIjogIkFwcCIsImF0dHJfX3N0eWxlIjogImNvbG9yOiByZ2IoNTIsIDYxLCA2Mik7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9faWQiOiAicm9vdCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImJvZHkiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDF9Cl0sInRva2VuIjogInhwOXFUMlZMWTc2SkpnIn19"
            },
        )

        self.assertEqual(
            patch_process_event_with_plugins.call_args[1]["args"][3]["properties"]["$elements"][0]["$el_text"],
            "💻 Writing code",
        )

    @patch("posthog.api.capture.celery_app.send_task")
    def test_js_gzip(self, patch_process_event_with_plugins):
        self.team.api_token = "rnEnwNvmHphTu5rFG4gWDDs49t00Vk50tDOeDdedMb4"
        self.team.save()

        self.client.post(
            "/track?compression=gzip-js",
            data=b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03\xadRKn\xdb0\x10\xbdJ@xi\xd9CY\xd6o[\xf7\xb3\xe8gS4\x8b\xa2\x10(r$\x11\xa6I\x81\xa2\xe4\x18A.\xd1\x0b\xf4 \xbdT\x8f\xd0a\x93&mQt\xd5\x15\xc9\xf7\xde\xbc\x19\xf0\xcd-\xc3\x05m`5;]\x92\xfb\xeb\x9a\x8d\xde\x8d\xe8\x83\xc6\x89\xd5\xb7l\xe5\xe8`\xaf\xb5\x9do\x88[\xb5\xde\x9d'\xf4\x04=\x1b\xbc;a\xc4\xe4\xec=\x956\xb37\x84\x0f!\x8c\xf5vk\x9c\x14fpS\xa8K\x00\xbeUNNQ\x1b\x11\x12\xfd\xceFb\x14a\xb0\x82\x0ck\xf6(~h\xd6,\xe8'\xed,\xab\xcb\x82\xd0IzD\xdb\x0c\xa8\xfb\x81\xbc8\x94\xf0\x84\x9e\xb5\n\x03\x81U\x1aA\xa3[\xf2;c\x1b\xdd\xe8\xf1\xe4\xc4\xf8\xa6\xd8\xec\x92\x16\x83\xd8T\x91\xd5\x96:\x85F+\xe2\xaa\xb44Gq\xe1\xb2\x0cp\x03\xbb\x1f\xf3\x05\x1dg\xe39\x14Y\x9a\xf3|\xb7\xe1\xb0[3\xa5\xa7\xa0\xad|\xa8\xe3E\x9e\xa5P\x89\xa2\xecv\xb2H k1\xcf\xabR\x08\x95\xa7\xfb\x84C\n\xbc\x856\xe1\x9d\xc8\x00\x92Gu\x05y\x0e\xb1\x87\xc2EK\xfc?^\xda\xea\xa0\x85i<vH\xf1\xc4\xc4VJ{\x941\xe2?Xm\xfbF\xb9\x93\xd0\xf1c~Q\xfd\xbd\xf6\xdf5B\x06\xbd`\xd3\xa1\x08\xb3\xa7\xd3\x88\x9e\x16\xe8#\x1b)\xec\xc1\xf5\x89\xf7\x14G2\x1aq!\xdf5\xebfc\x92Q\xf4\xf8\x13\xfat\xbf\x80d\xfa\xed\xcb\xe7\xafW\xd7\x9e\x06\xb5\xfd\x95t*\xeeZpG\x8c\r\xbd}n\xcfo\x97\xd3\xabqx?\xef\xfd\x8b\x97Y\x7f}8LY\x15\x00>\x1c\xf7\x10\x0e\xef\xf0\xa0P\xbdi3vw\xf7\x1d\xccN\xdf\x13\xe7\x02\x00\x00",
            content_type="text/plain",
        )

        self.assertEqual(patch_process_event_with_plugins.call_count, 1)
        self.assertEqual(patch_process_event_with_plugins.call_args[1]["args"][3]["event"], "my-event")
        self.assertEqual(
            patch_process_event_with_plugins.call_args[1]["args"][3]["properties"]["prop"], "💻 Writing code",
        )

    @patch("posthog.api.capture.celery_app.send_task")
    def test_js_gzip_with_no_content_type(self, patch_process_event_with_plugins):
        "IE11 sometimes does not send content_type"

        self.team.api_token = "rnEnwNvmHphTu5rFG4gWDDs49t00Vk50tDOeDdedMb4"
        self.team.save()

        self.client.post(
            "/track?compression=gzip-js",
            data=b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03\xadRKn\xdb0\x10\xbdJ@xi\xd9CY\xd6o[\xf7\xb3\xe8gS4\x8b\xa2\x10(r$\x11\xa6I\x81\xa2\xe4\x18A.\xd1\x0b\xf4 \xbdT\x8f\xd0a\x93&mQt\xd5\x15\xc9\xf7\xde\xbc\x19\xf0\xcd-\xc3\x05m`5;]\x92\xfb\xeb\x9a\x8d\xde\x8d\xe8\x83\xc6\x89\xd5\xb7l\xe5\xe8`\xaf\xb5\x9do\x88[\xb5\xde\x9d'\xf4\x04=\x1b\xbc;a\xc4\xe4\xec=\x956\xb37\x84\x0f!\x8c\xf5vk\x9c\x14fpS\xa8K\x00\xbeUNNQ\x1b\x11\x12\xfd\xceFb\x14a\xb0\x82\x0ck\xf6(~h\xd6,\xe8'\xed,\xab\xcb\x82\xd0IzD\xdb\x0c\xa8\xfb\x81\xbc8\x94\xf0\x84\x9e\xb5\n\x03\x81U\x1aA\xa3[\xf2;c\x1b\xdd\xe8\xf1\xe4\xc4\xf8\xa6\xd8\xec\x92\x16\x83\xd8T\x91\xd5\x96:\x85F+\xe2\xaa\xb44Gq\xe1\xb2\x0cp\x03\xbb\x1f\xf3\x05\x1dg\xe39\x14Y\x9a\xf3|\xb7\xe1\xb0[3\xa5\xa7\xa0\xad|\xa8\xe3E\x9e\xa5P\x89\xa2\xecv\xb2H k1\xcf\xabR\x08\x95\xa7\xfb\x84C\n\xbc\x856\xe1\x9d\xc8\x00\x92Gu\x05y\x0e\xb1\x87\xc2EK\xfc?^\xda\xea\xa0\x85i<vH\xf1\xc4\xc4VJ{\x941\xe2?Xm\xfbF\xb9\x93\xd0\xf1c~Q\xfd\xbd\xf6\xdf5B\x06\xbd`\xd3\xa1\x08\xb3\xa7\xd3\x88\x9e\x16\xe8#\x1b)\xec\xc1\xf5\x89\xf7\x14G2\x1aq!\xdf5\xebfc\x92Q\xf4\xf8\x13\xfat\xbf\x80d\xfa\xed\xcb\xe7\xafW\xd7\x9e\x06\xb5\xfd\x95t*\xeeZpG\x8c\r\xbd}n\xcfo\x97\xd3\xabqx?\xef\xfd\x8b\x97Y\x7f}8LY\x15\x00>\x1c\xf7\x10\x0e\xef\xf0\xa0P\xbdi3vw\xf7\x1d\xccN\xdf\x13\xe7\x02\x00\x00",
            content_type="",
        )

        self.assertEqual(patch_process_event_with_plugins.call_count, 1)
        self.assertEqual(patch_process_event_with_plugins.call_args[1]["args"][3]["event"], "my-event")
        self.assertEqual(
            patch_process_event_with_plugins.call_args[1]["args"][3]["properties"]["prop"], "💻 Writing code",
        )

    @patch("posthog.api.capture.celery_app.send_task")
    def test_invalid_gzip(self, patch_process_event_with_plugins):
        self.team.api_token = "rnEnwNvmHphTu5rFG4gWDDs49t00Vk50tDOeDdedMb4"
        self.team.save()

        response = self.client.post(
            "/track?compression=gzip", data=b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03", content_type="text/plain",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                "Malformed request data: Failed to decompress data. Compressed file ended before the end-of-stream marker was reached",
                code="invalid_payload",
            ),
        )
        self.assertEqual(patch_process_event_with_plugins.call_count, 0)

    @patch("posthog.api.capture.celery_app.send_task")
    def test_invalid_lz64(self, patch_process_event_with_plugins):
        self.team.api_token = "rnEnwNvmHphTu5rFG4gWDDs49t00Vk50tDOeDdedMb4"
        self.team.save()

        response = self.client.post("/track?compression=lz64", data="foo", content_type="text/plain",)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                "Malformed request data: Failed to decompress data.", code="invalid_payload",
            ),
        )
        self.assertEqual(patch_process_event_with_plugins.call_count, 0)

    @patch("posthog.api.capture.celery_app.send_task")
    def test_incorrect_padding(self, patch_process_event_with_plugins):
        response = self.client.get(
            "/e/?data=eyJldmVudCI6IndoYXRldmVmciIsInByb3BlcnRpZXMiOnsidG9rZW4iOiJ0b2tlbjEyMyIsImRpc3RpbmN0X2lkIjoiYXNkZiJ9fQ",
            content_type="application/json",
            HTTP_REFERER="https://localhost",
        )
        self.assertEqual(response.json()["status"], 1)
        self.assertEqual(patch_process_event_with_plugins.call_args[1]["args"][3]["event"], "whatevefr")

    @patch("posthog.api.capture.celery_app.send_task")
    def test_empty_request_returns_an_error(self, patch_process_event_with_plugins):
        """
        Empty requests that fail silently cause confusion as to whether they were successful or not.
        """

        # Empty GET
        response = self.client.get("/e/?data=", content_type="application/json", HTTP_ORIGIN="https://localhost",)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(patch_process_event_with_plugins.call_count, 0)

        # Empty POST
        response = self.client.post("/e/", {}, content_type="application/json", HTTP_ORIGIN="https://localhost",)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(patch_process_event_with_plugins.call_count, 0)

    @patch("posthog.api.capture.celery_app.send_task")
    def test_batch(self, patch_process_event_with_plugins):
        data = {"type": "capture", "event": "user signed up", "distinct_id": "2"}
        response = self.client.post(
            "/batch/", data={"api_key": self.team.api_token, "batch": [data]}, content_type="application/json",
        )
        arguments = self._to_arguments(patch_process_event_with_plugins)
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": {**data, "properties": {}},
                "team_id": self.team.pk,
            },
        )

    @patch("posthog.api.capture.celery_app.send_task")
    def test_batch_with_invalid_event(self, patch_process_event_with_plugins):
        data = [
            {"type": "capture", "event": "event1", "distinct_id": "2"},
            {"type": "capture", "event": "event2"},  # invalid
            {"type": "capture", "event": "event3", "distinct_id": "2"},
            {"type": "capture", "event": "event4", "distinct_id": "2"},
            {"type": "capture", "event": "event5", "distinct_id": "2"},
        ]
        response = self.client.post(
            "/batch/", data={"api_key": self.team.api_token, "batch": data}, content_type="application/json",
        )

        # We should return a 200 but not process the invalid event
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_process_event_with_plugins.call_count, 4)

        events_processed = [call.kwargs["args"][3]["event"] for call in patch_process_event_with_plugins.call_args_list]
        self.assertEqual(events_processed, ["event1", "event3", "event4", "event5"])  # event2 not processed

    @patch("posthog.api.capture.celery_app.send_task")
    def test_batch_gzip_header(self, patch_process_event_with_plugins):
        data = {
            "api_key": self.team.api_token,
            "batch": [{"type": "capture", "event": "user signed up", "distinct_id": "2",}],
        }

        response = self.client.generic(
            "POST",
            "/batch/",
            data=gzip.compress(json.dumps(data).encode()),
            content_type="application/json",
            HTTP_CONTENT_ENCODING="gzip",
        )

        arguments = self._to_arguments(patch_process_event_with_plugins)
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": {**data["batch"][0], "properties": {}},
                "team_id": self.team.pk,
            },
        )

    @patch("posthog.api.capture.celery_app.send_task")
    def test_batch_gzip_param(self, patch_process_event_with_plugins):
        data = {
            "api_key": self.team.api_token,
            "batch": [{"type": "capture", "event": "user signed up", "distinct_id": "2"}],
        }

        response = self.client.generic(
            "POST",
            "/batch/?compression=gzip",
            data=gzip.compress(json.dumps(data).encode()),
            content_type="application/json",
        )

        arguments = self._to_arguments(patch_process_event_with_plugins)
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": {**data["batch"][0], "properties": {}},
                "team_id": self.team.pk,
            },
        )

    @patch("posthog.api.capture.celery_app.send_task")
    def test_batch_lzstring(self, patch_process_event_with_plugins):
        data = {
            "api_key": self.team.api_token,
            "batch": [{"type": "capture", "event": "user signed up", "distinct_id": "2"}],
        }

        response = self.client.generic(
            "POST",
            "/batch",
            data=lzstring.LZString().compressToBase64(json.dumps(data)).encode(),
            content_type="application/json",
            HTTP_CONTENT_ENCODING="lz64",
        )

        arguments = self._to_arguments(patch_process_event_with_plugins)
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {
                "distinct_id": "2",
                "ip": "127.0.0.1",
                "site_url": "http://testserver",
                "data": {**data["batch"][0], "properties": {}},
                "team_id": self.team.pk,
            },
        )

    @patch("posthog.api.capture.celery_app.send_task")
    def test_lz64_with_emoji(self, patch_process_event_with_plugins):
        self.team.api_token = "KZZZeIpycLH-tKobLBET2NOg7wgJF2KqDL5yWU_7tZw"
        self.team.save()
        response = self.client.post(
            "/batch",
            data="NoKABBYN4EQKYDc4DsAuMBcYaD4NwyLswA0MADgE4D2JcZqAlnAM6bQwAkFzWMAsgIYBjMAHkAymAAaRdgCNKAd0Y0WMAMIALSgFs40tgICuZMilQB9IwBsV61KhIYA9I4CMAJgDsAOgAMvry4YABw+oY4AJnBaFHrqnOjc7t5+foEhoXokfKjqyHw6KhFRMcRschSKNGZIZIx0FMgsQQBspYwCJihm6nB0AOa2LC4+AKw+bR1wXfJ04TlDzSGllnQyKvJwa8ur1TR1DSou/j56dMhKtGaz6wBeAJ4GQagALPJ8buo3I8iLevQFWBczVGIxGAGYPABONxeMGQlzEcJ0Rj0ZACczXbg3OCQgBCyFxAlxAE1iQBBADSAC0ANYAVT4NIAKmDRC4eAA5AwAMUYABkAJIAcQMPCouOeZCCAFotAA1cLNeR6SIIOgCOBXcKHDwjSFBNyQnzA95BZ7SnxuAQjFwuABmYKCAg8bh8MqBYLgzRcIzc0pcfDgfD4Pn9uv1huNPhkwxGegMFy1KmxeIJRNJlNpDOZrPZXN5gpFYpIEqlsoVStOyDo9D4ljMJjtNBMZBsdgcziSxwCwVCPkclgofTOAH5kHAAB6oAC8jirNbodYbcCbxjOfTM4QoWj4Z0Onm7aT70hI8TiG5q+0aiQCzV80nUfEYZkYlkENLMGxkcQoNJYdrrJRSkEegkDMJtsiMTU7TfPouDAUBIGwED6nOaUDAnaVXWGdwYBAABdYhUF/FAVGpKkqTgAUSDuAQ+QACWlVAKQoGQ+VxABRJk3A5YQ+g8eQ+gAKW5NwKQARwAET5EY7gAdTpMwPFQKllQAX2ICg7TtJQEjAMFQmeNSCKAA==",
            content_type="application/json",
            HTTP_CONTENT_ENCODING="lz64",
        )
        self.assertEqual(response.status_code, 200)
        arguments = self._to_arguments(patch_process_event_with_plugins)
        self.assertEqual(arguments["data"]["event"], "🤓")

    def test_batch_incorrect_token(self):
        response = self.client.post(
            "/batch/",
            data={
                "api_key": "this-token-doesnt-exist",
                "batch": [{"type": "capture", "event": "user signed up", "distinct_id": "whatever",},],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json(),
            self.unauthenticated_response(
                "Project API key invalid. You can find your project API key in PostHog project settings.",
                code="invalid_api_key",
            ),
        )

    def test_batch_token_not_set(self):
        response = self.client.post(
            "/batch/",
            data={"batch": [{"type": "capture", "event": "user signed up", "distinct_id": "whatever",},]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json(),
            self.unauthenticated_response(
                "API key not provided. You can find your project API key in PostHog project settings.",
                code="missing_api_key",
            ),
        )

    @patch("statshog.defaults.django.statsd.incr")
    def test_batch_distinct_id_not_set(self, statsd_incr):
        response = self.client.post(
            "/batch/",
            data={"api_key": self.team.api_token, "batch": [{"type": "capture", "event": "user signed up",},],},
            content_type="application/json",
        )

        # An invalid distinct ID will not return an error code, instead we will capture an exception
        # and will not ingest the event
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # endpoint success metric + missing ID metric
        self.assertEqual(statsd_incr.call_count, 2)

        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], "invalid_event")
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"error": "missing_distinct_id"}})

    @patch("posthog.api.capture.celery_app.send_task")
    def test_engage(self, patch_process_event_with_plugins):
        response = self.client.get(
            "/engage/?data=%s"
            % quote(
                self._to_json(
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
        arguments = self._to_arguments(patch_process_event_with_plugins)
        self.assertEqual(arguments["data"]["event"], "$identify")
        arguments.pop("now")  # can't compare fakedate
        arguments.pop("sent_at")  # can't compare fakedate
        arguments.pop("data")  # can't compare fakedate
        self.assertDictEqual(
            arguments,
            {"distinct_id": "3", "ip": "127.0.0.1", "site_url": "http://testserver", "team_id": self.team.pk,},
        )

    @patch("posthog.api.capture.celery_app.send_task")
    def test_python_library(self, patch_process_event_with_plugins):
        self.client.post(
            "/track/",
            data={
                "data": self._dict_to_b64({"event": "$pageview", "properties": {"distinct_id": "eeee",},}),
                "api_key": self.team.api_token,  # main difference in this test
            },
        )
        arguments = self._to_arguments(patch_process_event_with_plugins)
        self.assertEqual(arguments["team_id"], self.team.pk)

    @patch("posthog.api.capture.celery_app.send_task")
    def test_base64_decode_variations(self, patch_process_event_with_plugins):
        base64 = "eyJldmVudCI6IiRwYWdldmlldyIsInByb3BlcnRpZXMiOnsiZGlzdGluY3RfaWQiOiJlZWVlZWVlZ8+lZWVlZWUifX0="
        dict = self._dict_from_b64(base64)
        self.assertDictEqual(
            dict, {"event": "$pageview", "properties": {"distinct_id": "eeeeeeegϥeeeee",},},
        )

        # POST with "+" in the base64
        self.client.post(
            "/track/", data={"data": base64, "api_key": self.team.api_token,},  # main difference in this test
        )
        arguments = self._to_arguments(patch_process_event_with_plugins)
        self.assertEqual(arguments["team_id"], self.team.pk)
        self.assertEqual(arguments["distinct_id"], "eeeeeeegϥeeeee")

        # POST with " " in the base64 instead of the "+"
        self.client.post(
            "/track/",
            data={"data": base64.replace("+", " "), "api_key": self.team.api_token,},  # main difference in this test
        )
        arguments = self._to_arguments(patch_process_event_with_plugins)
        self.assertEqual(arguments["team_id"], self.team.pk)
        self.assertEqual(arguments["distinct_id"], "eeeeeeegϥeeeee")

    @patch("posthog.api.capture.celery_app.send_task")
    def test_js_library_underscore_sent_at(self, patch_process_event_with_plugins):
        now = timezone.now()
        tomorrow = now + timedelta(days=1, hours=2)
        tomorrow_sent_at = now + timedelta(days=1, hours=2, minutes=10)

        data = {
            "event": "movie played",
            "timestamp": tomorrow.isoformat(),
            "properties": {"distinct_id": 2, "token": self.team.api_token},
        }

        self.client.get(
            "/e/?_=%s&data=%s" % (int(tomorrow_sent_at.timestamp()), quote(self._to_json(data))),
            content_type="application/json",
            HTTP_ORIGIN="https://localhost",
        )

        arguments = self._to_arguments(patch_process_event_with_plugins)
        arguments.pop("now")  # can't compare fakedate

        # right time sent as sent_at to process_event

        self.assertEqual(arguments["sent_at"].tzinfo, timezone.utc)

        timediff = arguments["sent_at"].timestamp() - tomorrow_sent_at.timestamp()
        self.assertLess(abs(timediff), 1)
        self.assertEqual(arguments["data"]["timestamp"], tomorrow.isoformat())

    @patch("posthog.api.capture.celery_app.send_task")
    def test_long_distinct_id(self, patch_process_event_with_plugins):
        now = timezone.now()
        tomorrow = now + timedelta(days=1, hours=2)
        tomorrow_sent_at = now + timedelta(days=1, hours=2, minutes=10)

        data = {
            "event": "movie played",
            "timestamp": tomorrow.isoformat(),
            "properties": {"distinct_id": "a" * 250, "token": self.team.api_token},
        }

        self.client.get(
            "/e/?_=%s&data=%s" % (int(tomorrow_sent_at.timestamp()), quote(self._to_json(data))),
            content_type="application/json",
            HTTP_ORIGIN="https://localhost",
        )
        arguments = self._to_arguments(patch_process_event_with_plugins)
        self.assertEqual(len(arguments["distinct_id"]), 200)

    @patch("posthog.api.capture.celery_app.send_task")
    def test_sent_at_field(self, patch_process_event_with_plugins):
        now = timezone.now()
        tomorrow = now + timedelta(days=1, hours=2)
        tomorrow_sent_at = now + timedelta(days=1, hours=2, minutes=10)

        self.client.post(
            "/track",
            data={
                "sent_at": tomorrow_sent_at.isoformat(),
                "data": self._dict_to_b64(
                    {"event": "$pageview", "timestamp": tomorrow.isoformat(), "properties": {"distinct_id": "eeee",},}
                ),
                "api_key": self.team.api_token,  # main difference in this test
            },
        )

        arguments = self._to_arguments(patch_process_event_with_plugins)
        arguments.pop("now")  # can't compare fakedate

        # right time sent as sent_at to process_event
        timediff = arguments["sent_at"].timestamp() - tomorrow_sent_at.timestamp()
        self.assertLess(abs(timediff), 1)
        self.assertEqual(arguments["data"]["timestamp"], tomorrow.isoformat())

    def test_incorrect_json(self):
        response = self.client.post(
            "/capture/", '{"event": "incorrect json with trailing comma",}', content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                "Malformed request data: Invalid JSON: Expecting property name enclosed in double quotes: line 1 column 48 (char 47)",
                code="invalid_payload",
            ),
        )

    @patch("statshog.defaults.django.statsd.incr")
    def test_distinct_id_nan(self, statsd_incr):
        response = self.client.post(
            "/track/",
            data={
                "data": json.dumps([{"event": "beep", "properties": {"distinct_id": float("nan")}}]),
                "api_key": self.team.api_token,
            },
        )

        # An invalid distinct ID will not return an error code, instead we will capture an exception
        # and will not ingest the event
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # endpoint success metric + invalid ID metric
        self.assertEqual(statsd_incr.call_count, 2)

        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], "invalid_event")
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"error": "invalid_distinct_id"}})

    @patch("statshog.defaults.django.statsd.incr")
    def test_distinct_id_set_but_null(self, statsd_incr):
        response = self.client.post(
            "/e/",
            data={"api_key": self.team.api_token, "type": "capture", "event": "user signed up", "distinct_id": None},
            content_type="application/json",
        )

        # An invalid distinct ID will not return an error code, instead we will capture an exception
        # and will not ingest the event
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # endpoint success metric + invalid ID metric
        self.assertEqual(statsd_incr.call_count, 2)

        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], "invalid_event")
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"error": "invalid_distinct_id"}})

    @patch("statshog.defaults.django.statsd.incr")
    def test_event_name_missing(self, statsd_incr):
        response = self.client.post(
            "/e/",
            data={"api_key": self.team.api_token, "type": "capture", "event": "", "distinct_id": "a valid id"},
            content_type="application/json",
        )

        # An invalid distinct ID will not return an error code, instead we will capture an exception
        # and will not ingest the event
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # endpoint success metric + invalid ID metric
        self.assertEqual(statsd_incr.call_count, 2)

        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], "invalid_event")
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"error": "missing_event_name"}})

    @patch("posthog.api.capture.celery_app.send_task")
    def test_add_feature_flags_if_missing(self, patch_process_event_with_plugins) -> None:
        self.assertListEqual(self.team.event_properties_numerical, [])
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="test-ff", rollout_percentage=100)
        self.client.post(
            "/track/",
            data={
                "data": json.dumps([{"event": "purchase", "properties": {"distinct_id": "xxx", "$lib": "web"}}]),
                "api_key": self.team.api_token,
            },
        )
        arguments = self._to_arguments(patch_process_event_with_plugins)
        self.assertEqual(arguments["data"]["properties"]["$active_feature_flags"], ["test-ff"])

    @patch("posthog.api.capture.celery_app.send_task")
    def test_add_feature_flags_with_overrides_if_missing(self, patch_process_event_with_plugins) -> None:
        feature_flag_instance = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="test-ff", rollout_percentage=0
        )
        Person.objects.create(
            team=self.team, distinct_ids=[self.user.distinct_id], properties={"email": self.user.email},
        )
        FeatureFlagOverride.objects.create(
            team=self.team, user=self.user, feature_flag=feature_flag_instance, override_value=True
        )
        self.client.post(
            "/track/",
            data={
                "data": json.dumps(
                    [{"event": "purchase", "properties": {"distinct_id": self.user.distinct_id, "$lib": "web"}}]
                ),
                "api_key": self.team.api_token,
            },
        )
        arguments = self._to_arguments(patch_process_event_with_plugins)
        self.assertEqual(arguments["data"]["properties"]["$feature/test-ff"], True)
        self.assertEqual(arguments["data"]["properties"]["$active_feature_flags"], ["test-ff"])

    def test_handle_lacking_event_name_field(self):
        response = self.client.post(
            "/e/",
            data={"distinct_id": "abc", "properties": {"cost": 2}, "api_key": self.team.api_token},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                'Invalid payload: All events must have the event name field "event"!', code="invalid_payload",
            ),
        )

    def test_handle_invalid_snapshot(self):
        response = self.client.post(
            "/e/",
            data={"event": "$snapshot", "distinct_id": "abc", "api_key": self.team.api_token},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                'Invalid payload: $snapshot events must contain property "$snapshot_data"!', code="invalid_payload",
            ),
        )

    def test_batch_request_with_invalid_auth(self):
        data = [
            {
                "event": "$pageleave",
                "project_id": self.team.id,
                "properties": {
                    "$os": "Linux",
                    "$browser": "Chrome",
                    "token": "fake token",  # as this is invalid, will do API key authentication
                },
                "timestamp": "2021-04-20T19:11:33.841Z",
            }
        ]
        response = self.client.get("/e/?data=%s" % quote(self._to_json(data)))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json(),
            {
                "type": "authentication_error",
                "code": "invalid_personal_api_key",
                "detail": "Invalid Personal API key.",
                "attr": None,
            },
        )

    # On CH deployments the events sent would be added to a Kafka dead letter queue
    # On Postgres deployments we return a 503: Service Unavailable, and capture an
    # exception in Sentry
    @patch("statshog.defaults.django.statsd.incr")
    @patch("sentry_sdk.capture_exception")
    @patch("posthog.models.Team.objects.get_team_from_token", side_effect=mocked_get_team_from_token)
    def test_fetch_team_failure(self, get_team_from_token, capture_exception, statsd_incr):
        response = self.client.post(
            "/track/",
            data={
                "data": json.dumps(
                    {"event": "some event", "properties": {"distinct_id": "valid id", "token": self.team.api_token,},},
                ),
                "api_key": self.team.api_token,
            },
        )

        # self.assertEqual(capture_exception.call_count, 1)
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["code"], "fetch_team_fail")

        self.assertEqual(get_team_from_token.call_args.args[0], "token123")
        self.assertEqual(statsd_incr.call_args.args[0], "posthog_cloud_raw_endpoint_exception")

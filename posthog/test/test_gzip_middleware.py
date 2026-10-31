import re

from posthog.test.base import APIBaseTest
from pytest import raises

from django.conf import settings
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.gzip_middleware import InvalidGZipAllowList, allowed_path

custom_headers = {"HTTP_ACCEPT_ENCODING": "gzip"}


class TestGzipMiddleware(APIBaseTest):
    def _get_path(self, path):
        return self.client.get(path, data=None, follow=False, secure=False, **custom_headers)

    def test_does_not_compress_outside_of_allow_list(self) -> None:
        with self.settings(GZIP_RESPONSE_ALLOW_LIST=["something-else", "not-root"]):
            response = self._get_path("/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            contentEncoding = response.headers.get("Content-Encoding", None)
            self.assertEqual(contentEncoding, None)

    def test_no_compression_for_unsuccessful_requests_to_paths_on_the_allow_list(self) -> None:
        with self.settings(GZIP_RESPONSE_ALLOW_LIST=["something-else", "snapshots$"]):
            response = self._get_path(f"/api/projects/{self.team.pk}/session_recordings/blah/snapshots")
            self.assertEqual(
                response.status_code,
                status.HTTP_404_NOT_FOUND,
                msg=response.content.decode("utf-8"),
            )

            contentEncoding = response.headers.get("Content-Encoding", None)
            self.assertEqual(contentEncoding, None)

    def test_no_compression_when_allow_list_is_empty(self) -> None:
        with self.settings(GZIP_RESPONSE_ALLOW_LIST=[]):
            response = self._get_path("/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            contentEncoding = response.headers.get("Content-Encoding", None)
            self.assertEqual(contentEncoding, None)

    def test_sensible_error_if_bad_pattern(self) -> None:
        with raises(InvalidGZipAllowList):
            with self.settings(GZIP_RESPONSE_ALLOW_LIST=["(((("]):
                self._get_path("/")


class TestGzipAllowList(SimpleTestCase):
    @parameterized.expand(
        [
            ("logs", "logs/", True),
            ("log_entries", "log_entries/", True),
            ("log_entries_without_slash", "log_entries", True),
            ("session_logs", "session_logs/", True),
            ("sse_stream", "stream/", False),
            ("stream_token", "stream_token/", False),
            ("run_detail", "", False),
        ]
    )
    def test_task_run_paths(self, _name: str, suffix: str, compressed: bool) -> None:
        patterns = [re.compile(pattern) for pattern in settings.GZIP_RESPONSE_ALLOW_LIST]
        path = f"/api/projects/2/tasks/0190a000-0000-4000-8000-0000000000a1/runs/0190a000-0000-4000-8000-0000000000b2/{suffix}"
        self.assertEqual(allowed_path(path, patterns), compressed)

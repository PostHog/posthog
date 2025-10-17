from posthog.test.base import APIBaseTest
from pytest import raises
from unittest import skip

from rest_framework import status

from posthog.gzip_middleware import InvalidGZipAllowList

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

    @skip("fails in CI, but covered by test in test_clickhouse_session_recording")
    def test_compresses_when_on_allow_list(self) -> None:
        with self.settings(GZIP_RESPONSE_ALLOW_LIST=["something-else", "/home"]):
            response = self._get_path("/home")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            contentEncoding = response.headers.get("Content-Encoding", None)
            self.assertEqual(contentEncoding, "gzip")

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

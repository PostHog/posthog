from rest_framework import status

from posthog.test.base import APIBaseTest

custom_headers = {"HTTP_ACCEPT_ENCODING": "gzip"}


class TestGzipMiddleware(APIBaseTest):
    def test_does_not_compress_outside_of_allow_list(self) -> None:

        response = self.client.get("/", data=None, follow=False, secure=False, **custom_headers,)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        contentEncoding = response.headers.get("Content-Encoding", None)
        self.assertEqual(contentEncoding, None)

    def test_no_compression_for_unsuccessful_requests_to_paths_on_the_allow_list(self) -> None:
        response = self.client.get(
            "/api/projects/12/session_recordings/blah/snapshots",
            data=None,
            follow=False,
            secure=False,
            **custom_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        contentEncoding = response.headers.get("Content-Encoding", None)
        self.assertEqual(contentEncoding, None)

from django.http import HttpRequest, HttpResponse
from django.test import TestCase

from posthog.utils_cors import cors_response


class FakeRequest(HttpRequest):
    def __init__(self, META):
        super().__init__()
        self.META = META


class TestCorsResponse(TestCase):
    def test_origin(self) -> None:
        valid_origin_test_cases = [
            ("https://my-amazing.site", "https://my-amazing.site"),
            ("https://my-amazing.site/", "https://my-amazing.site"),
            ("https://my-amazing.site/my/path", "https://my-amazing.site"),
            ("http://my-amazing.site/my/path", "http://my-amazing.site"),
            ("https://us.posthog.com/decide", "https://us.posthog.com"),
            ("my-amazing.site", "*"),
            ("my-amazing.site/path", "*"),
            ("null", "*"),
            ("", None),
        ]

        for origin, expected in valid_origin_test_cases:
            with self.subTest():
                request = FakeRequest(META={"HTTP_ORIGIN": origin})
                self.assertEqual(
                    expected,
                    cors_response(request, HttpResponse()).get("Access-Control-Allow-Origin"),
                    msg=f"with origin='{origin}', actual did not equal {expected}",
                )

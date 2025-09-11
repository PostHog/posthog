from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.utils import PotentialSecurityProblemException, absolute_uri


class TestCSVExporterURLSanitization(APIBaseTest):
    def test_sanitize_url_when_provided_path(self) -> None:
        with self.settings(SITE_URL="https://something.posthog.com"):
            sanitised = absolute_uri(None or "/some/location")
            assert sanitised == "https://something.posthog.com/some/location"

    def test_sanitize_url_when_provided_path_and_site_url_has_a_port(self) -> None:
        with self.settings(SITE_URL="https://localhost:8000"):
            sanitised = absolute_uri(None or "/some/location")
            assert sanitised == "https://localhost:8000/some/location"

    error_test_cases = [
        (
            "changing scheme",
            "https://localhost:8000",
            "http://localhost:8000/some/location",
        ),
        (
            "changing port",
            "https://localhost:8000",
            "https://localhost:8123/some/location",
        ),
        (
            "changing port and url",
            "https://something.posthog.com:8000",
            "https://localhost:8123/some/location",
        ),
        (
            "changing domain",
            "https://app.posthog.com",
            "https://google.com/some/location",
        ),
    ]

    @parameterized.expand(error_test_cases)
    def test_sanitise_url_error_cases_as_paths(self, _name, site_url, provided_url_or_path) -> None:
        with self.settings(SITE_URL=site_url), self.assertRaises(PotentialSecurityProblemException):
            absolute_uri(None or provided_url_or_path)

    @parameterized.expand(error_test_cases)
    def test_sanitise_url_error_cases_as_next_url(self, _name, site_url, provided_url_or_path) -> None:
        with self.settings(SITE_URL=site_url), self.assertRaises(PotentialSecurityProblemException):
            absolute_uri(provided_url_or_path or None)

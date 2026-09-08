from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.csrf import CSRF_ORIGIN_REJECTED_CODE, CSRF_TOKEN_INVALID_CODE, csrf_failure_code


class TestCsrfFailureCode(SimpleTestCase):
    @parameterized.expand(
        [
            ("CSRF cookie not set.", CSRF_TOKEN_INVALID_CODE),
            ("CSRF token missing.", CSRF_TOKEN_INVALID_CODE),
            ("CSRF cookie has incorrect length.", CSRF_TOKEN_INVALID_CODE),
            ("CSRF token from the 'X-Csrftoken' HTTP header incorrect.", CSRF_TOKEN_INVALID_CODE),
            (
                "Origin checking failed - https://evil.example.com does not match any trusted origins.",
                CSRF_ORIGIN_REJECTED_CODE,
            ),
            (
                "Referer checking failed - https://evil.example.com does not match any trusted origins.",
                CSRF_ORIGIN_REJECTED_CODE,
            ),
            ("Referer checking failed - no Referer.", CSRF_ORIGIN_REJECTED_CODE),
            ("Referer checking failed - Referer is malformed.", CSRF_ORIGIN_REJECTED_CODE),
        ]
    )
    def test_classifies_django_rejection_reason(self, reason: str, expected_code: str) -> None:
        assert csrf_failure_code(reason) == expected_code


class TestCsrfTokenEndpoint(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def test_issues_a_csrf_cookie_without_a_session(self) -> None:
        response = self.client.get("/api/csrf_token/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.cookies["posthog_csrftoken"].value


class TestCsrfRejectionCode(APIBaseTest):
    @parameterized.expand(
        [
            ("no token at all", {}, CSRF_TOKEN_INVALID_CODE),
            ("an untrusted Origin", {"Origin": "https://evil.example.com"}, CSRF_ORIGIN_REJECTED_CODE),
        ]
    )
    def test_a_rejected_write_carries_the_code_for_its_cause(
        self, _name: str, headers: dict[str, str], expected_code: str
    ) -> None:
        # The frontend keys its recovery on these codes. Reported as `permission_denied`, as they
        # were, a stale token is indistinguishable from having no access to the resource.
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            f"/api/projects/{self.team.id}/cohorts/", {"name": "cohort"}, format="json", headers=headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == expected_code

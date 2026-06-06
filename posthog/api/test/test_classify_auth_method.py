from django.test import TestCase

from parameterized import parameterized

from posthog.auth import (
    JwtAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    ProjectSecretAPIKeyAuthentication,
    SessionAuthentication,
)

from products.feature_flags.backend.api.feature_flag import _classify_auth_method


class TestClassifyAuthMethod(TestCase):
    @parameterized.expand(
        [
            (ProjectSecretAPIKeyAuthentication(), "secret_api_key"),
            (PersonalAPIKeyAuthentication(), "personal_api_key"),
            (OAuthAccessTokenAuthentication(), "oauth"),
            (JwtAuthentication(), "jwt"),
            (SessionAuthentication(), "session"),
            (None, "other"),
            ("unexpected_type", "other"),
        ]
    )
    def test_returns_expected_label(self, authenticator, expected):
        self.assertEqual(_classify_auth_method(authenticator), expected)

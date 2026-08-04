from django.contrib.auth.hashers import make_password
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.oauth.client_auth import verify_client_secret
from posthog.api.oauth.views import OAuthValidator


class TestVerifyClientSecret(SimpleTestCase):
    @parameterized.expand(
        [
            ("correct_hashed", "s3cret", make_password("s3cret"), True),
            ("wrong_hashed", "wrong", make_password("s3cret"), False),
            ("correct_unhashed_legacy", "s3cret", "s3cret", True),
            ("wrong_unhashed_legacy", "wrong", "s3cret", False),
            # An app created with client_secret="" stores make_password(""), a valid hash of
            # the empty string, so a bare check_password would authenticate any caller that
            # presents no secret. Applications registered for private_key_jwt are exactly that
            # shape, since their proof is a signed assertion and they hold no secret.
            ("blank_provided_against_hash_of_blank", "", make_password(""), False),
            ("blank_provided_against_real_secret", "", make_password("s3cret"), False),
            ("blank_stored", "s3cret", "", False),
        ]
    )
    def test_verify_client_secret(self, _name, provided, stored, expected):
        assert verify_client_secret(provided, stored) is expected

    def test_validator_rejects_a_blank_secret(self):
        # The library's own _check_secret accepts this, so the override is what stands between
        # a credential-less request and every confidential app that holds no secret.
        assert OAuthValidator()._check_secret("", make_password("")) is False
        assert OAuthValidator()._check_secret("s3cret", make_password("s3cret")) is True

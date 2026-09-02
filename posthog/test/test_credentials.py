from django.test import SimpleTestCase

from posthog.credentials import AWSKeyPair


class TestAWSKeyPair(SimpleTestCase):
    def test_secret_is_absent_from_repr_but_still_readable(self):
        pair = AWSKeyPair.unsafe_from_strings("AKIAEXAMPLE", "the-secret")

        # A traceback or log line that captures the object must not print the secret.
        assert "the-secret" not in repr(pair)
        assert "AKIAEXAMPLE" in repr(pair)
        assert pair.secret_access_key == "the-secret"

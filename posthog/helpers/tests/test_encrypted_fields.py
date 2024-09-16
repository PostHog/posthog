from unittest.mock import patch

from freezegun import freeze_time

from posthog.helpers.encrypted_fields import EncryptedFieldMixin
from posthog.test.base import BaseTest


class TestEncryptedFields(BaseTest):
    def test_simple_encryption_and_decryption(self):
        """
        Simple test case to be replicated in node tests or anywhere else that the same secrets will be used
        """
        ef = EncryptedFieldMixin()
        with freeze_time("2024-01-01T00:01:00Z"):
            with patch("os.urandom", return_value=b"\x00" * 16):
                encrypted = ef.f.encrypt(bytes("test-case", "utf-8")).decode("utf-8")

        assert (
            encrypted
            == "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAEN-py1-Ob8hr3zEp5LsfNqusw0ovJsBR3jbfRxnBhPcv3xe1hmNpEPdNXU5Xv47OQ=="
        )
        decrypted = ef.f.decrypt(bytes(encrypted, "utf-8")).decode("utf-8")

        assert decrypted == "test-case"

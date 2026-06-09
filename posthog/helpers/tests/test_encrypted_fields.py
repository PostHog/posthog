import base64

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from cryptography.fernet import Fernet, InvalidToken
from parameterized import parameterized

from posthog.helpers.encrypted_fields import EncryptedFieldMixin

KEY_A = "a" * 32
KEY_B = "b" * 32
KEY_C = "c" * 32

OLD = "o" * 32
NEW = "n" * 32
PLAINTEXT = "super-secret-value"


def _fernet(raw_key: str) -> Fernet:
    # Build a Fernet from a single raw salt key, matching EncryptedFieldMixin.keys derivation
    return Fernet(base64.urlsafe_b64encode(raw_key.encode("utf-8")))


def _encrypt_with(keys: list[str], plaintext: str = PLAINTEXT) -> str:
    # Simulates an app running with the given ENCRYPTION_SALT_KEYS encrypting a value
    with override_settings(ENCRYPTION_SALT_KEYS=keys, SALT_KEY=[]):
        return EncryptedFieldMixin().encrypt(plaintext)


def _decrypt_with(keys: list[str], token: str) -> str:
    # Simulates an app running with the given ENCRYPTION_SALT_KEYS decrypting a value
    with override_settings(ENCRYPTION_SALT_KEYS=keys, SALT_KEY=[]):
        return EncryptedFieldMixin().decrypt(token)


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
            == "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAP89mTGU6xUyLcVUIB4ySnX2Y8ZgwLALpzYGfm76Fk64vPRY62flSIigMa_MqTlKyA=="
        )
        decrypted = ef.f.decrypt(bytes(encrypted, "utf-8")).decode("utf-8")

        assert decrypted == "test-case"


class TestEncryptedFieldsMultiKey(SimpleTestCase):
    # SALT_KEY=[] disables the legacy PBKDF2-derived keys so each test only exercises ENCRYPTION_SALT_KEYS

    @override_settings(ENCRYPTION_SALT_KEYS=[KEY_A, KEY_B], SALT_KEY=[])
    def test_encryption_uses_first_key(self):
        token = EncryptedFieldMixin().encrypt("secret")

        assert _fernet(KEY_A).decrypt(token.encode("utf-8")).decode("utf-8") == "secret"
        with self.assertRaises(InvalidToken):
            _fernet(KEY_B).decrypt(token.encode("utf-8"))

    def test_decryption_tries_every_key_in_the_list(self):
        with override_settings(ENCRYPTION_SALT_KEYS=[KEY_B], SALT_KEY=[]):
            token = EncryptedFieldMixin().encrypt("secret")

        with override_settings(ENCRYPTION_SALT_KEYS=[KEY_A, KEY_B], SALT_KEY=[]):
            assert EncryptedFieldMixin().decrypt(token) == "secret"

    def test_prepending_new_key_keeps_old_data_readable_and_writes_with_new(self):
        with override_settings(ENCRYPTION_SALT_KEYS=[KEY_B], SALT_KEY=[]):
            old_token = EncryptedFieldMixin().encrypt("secret")

        with override_settings(ENCRYPTION_SALT_KEYS=[KEY_A, KEY_B], SALT_KEY=[]):
            ef = EncryptedFieldMixin()
            assert ef.decrypt(old_token) == "secret"
            new_token = ef.encrypt("secret")

        assert _fernet(KEY_A).decrypt(new_token.encode("utf-8")).decode("utf-8") == "secret"

    def test_removing_old_key_makes_old_data_undecryptable(self):
        with override_settings(ENCRYPTION_SALT_KEYS=[KEY_B], SALT_KEY=[]):
            old_token = EncryptedFieldMixin().encrypt("secret")

        with override_settings(ENCRYPTION_SALT_KEYS=[KEY_A], SALT_KEY=[]):
            with self.assertRaises(InvalidToken):
                EncryptedFieldMixin().decrypt(old_token)

    @override_settings(ENCRYPTION_SALT_KEYS=[KEY_B, KEY_A], SALT_KEY=[])
    def test_key_order_determines_which_key_encrypts(self):
        token = EncryptedFieldMixin().encrypt("secret")

        assert _fernet(KEY_B).decrypt(token.encode("utf-8")).decode("utf-8") == "secret"
        with self.assertRaises(InvalidToken):
            _fernet(KEY_A).decrypt(token.encode("utf-8"))

    def test_three_keys_decrypt_data_from_any_of_them(self):
        tokens = {}
        for key in (KEY_A, KEY_B, KEY_C):
            with override_settings(ENCRYPTION_SALT_KEYS=[key], SALT_KEY=[]):
                tokens[key] = EncryptedFieldMixin().encrypt(f"secret-{key[0]}")

        with override_settings(ENCRYPTION_SALT_KEYS=[KEY_C, KEY_B, KEY_A], SALT_KEY=[]):
            ef = EncryptedFieldMixin()
            for key in (KEY_A, KEY_B, KEY_C):
                assert ef.decrypt(tokens[key]) == f"secret-{key[0]}"


class TestEncryptionKeyRotationTwoStep(SimpleTestCase):
    # Two-step rollout, used because apps are not guaranteed to redeploy simultaneously:
    #   step 1: [OLD] -> [OLD, NEW]      NEW added for decryption; OLD still encrypts
    #   step 2: [OLD, NEW] -> [NEW, OLD] NEW now encrypts; OLD kept for decryption
    # Safety invariant: within each step's mixed-version window, every running app can
    # decrypt whatever any other running app writes.

    @parameterized.expand(
        [
            ("step_1", [[OLD], [OLD, NEW]]),
            ("step_2", [[OLD, NEW], [NEW, OLD]]),
        ]
    )
    def test_coexisting_apps_decrypt_each_others_writes(self, _name, coexisting):
        for writer_keys in coexisting:
            token = _encrypt_with(writer_keys)
            for reader_keys in coexisting:
                assert _decrypt_with(reader_keys, token) == PLAINTEXT

    @parameterized.expand(
        [
            ("old_only", [OLD]),
            ("old_then_new", [OLD, NEW]),
        ]
    )
    def test_step_1_apps_always_encrypt_with_old_key(self, _name, keys):
        # While [OLD] and [OLD, NEW] apps coexist, OLD is always first, so no app emits
        # NEW-encrypted data that an un-upgraded [OLD]-only app could not read.
        token = _encrypt_with(keys)
        assert _fernet(OLD).decrypt(token.encode("utf-8")).decode("utf-8") == PLAINTEXT
        with self.assertRaises(InvalidToken):
            _fernet(NEW).decrypt(token.encode("utf-8"))

    def test_step_2_apps_encrypt_with_new_key(self):
        token = _encrypt_with([NEW, OLD])
        assert _fernet(NEW).decrypt(token.encode("utf-8")).decode("utf-8") == PLAINTEXT

    def test_skipping_step_1_would_break_un_upgraded_apps(self):
        # Justifies the two-step: a direct [OLD] -> [NEW, OLD] jump lets an upgraded app
        # encrypt with NEW while an un-upgraded [OLD]-only app still cannot decrypt it.
        token = _encrypt_with([NEW, OLD])
        with self.assertRaises(InvalidToken):
            _decrypt_with([OLD], token)

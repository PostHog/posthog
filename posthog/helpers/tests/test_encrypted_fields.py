import base64

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from parameterized import parameterized

from posthog.helpers.encrypted_fields import EncryptedFieldMixin, check_encryption_salt_keys
from posthog.settings.utils import get_list

KEY_A = "a" * 32
KEY_B = "b" * 32
KEY_C = "c" * 32

OLD = "o" * 32
NEW = "n" * 32
SALT = "legacy-salt-key"
PLAINTEXT = "super-secret-value"


def _fernet(raw_key: str) -> Fernet:
    # Build a Fernet from a single raw salt key, matching EncryptedFieldMixin.keys derivation
    return Fernet(base64.urlsafe_b64encode(raw_key.encode("utf-8")))


def _legacy_fernet(secret_key: str, salt_key: str = SALT) -> Fernet:
    # Reproduces the legacy PBKDF2(SECRET_KEY, salt=SALT_KEY) derivation in EncryptedFieldMixin.keys
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt_key.encode("utf-8"),
        iterations=100000,
        backend=default_backend(),
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(secret_key.encode("utf-8"))))


def _legacy_token(secret_key: str, plaintext: str = PLAINTEXT) -> str:
    # A value as it was written in the pre-ENCRYPTION_SALT_KEYS era, encrypted under the SECRET_KEY
    return _legacy_fernet(secret_key).encrypt(plaintext.encode("utf-8")).decode("utf-8")


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


class TestSecretKeyRotation(SimpleTestCase):
    # Legacy rows were encrypted under PBKDF2(SECRET_KEY, salt=SALT_KEY). Rotating SECRET_KEY must
    # keep them decryptable via SECRET_KEY_FALLBACKS, otherwise the rotation strands them forever.

    @override_settings(SECRET_KEY=OLD, SECRET_KEY_FALLBACKS=[], SALT_KEY=[SALT], ENCRYPTION_SALT_KEYS=[KEY_A])
    def test_legacy_value_decrypts_before_rotation(self):
        assert EncryptedFieldMixin().decrypt(_legacy_token(OLD)) == PLAINTEXT

    @override_settings(SECRET_KEY=NEW, SECRET_KEY_FALLBACKS=[OLD], SALT_KEY=[SALT], ENCRYPTION_SALT_KEYS=[KEY_A])
    def test_legacy_value_decrypts_after_rotation_via_fallback(self):
        # OLD has moved out of SECRET_KEY into SECRET_KEY_FALLBACKS; legacy data must still read
        assert EncryptedFieldMixin().decrypt(_legacy_token(OLD)) == PLAINTEXT

    @override_settings(SECRET_KEY=NEW, SECRET_KEY_FALLBACKS=[], SALT_KEY=[SALT], ENCRYPTION_SALT_KEYS=[KEY_A])
    def test_rotation_without_fallback_strands_legacy_value(self):
        # Documents the data-loss failure mode the fallback support prevents
        with self.assertRaises(InvalidToken):
            EncryptedFieldMixin().decrypt(_legacy_token(OLD))

    @override_settings(SECRET_KEY=NEW, SECRET_KEY_FALLBACKS=[OLD], SALT_KEY=[SALT], ENCRYPTION_SALT_KEYS=[KEY_A])
    def test_new_writes_use_encryption_salt_keys_not_secret_derived_key(self):
        # The SECRET_KEY-derived keys are decrypt-only; new values must encrypt under ENCRYPTION_SALT_KEYS[0]
        token = EncryptedFieldMixin().encrypt(PLAINTEXT)

        assert _fernet(KEY_A).decrypt(token.encode("utf-8")).decode("utf-8") == PLAINTEXT
        with self.assertRaises(InvalidToken):
            _legacy_fernet(NEW).decrypt(token.encode("utf-8"))


class TestEncryptionSaltKeysCheck(SimpleTestCase):
    # System check that ENCRYPTION_SALT_KEYS entries are valid Fernet keys (exactly 32 bytes). Each is
    # used directly as a Fernet key, so a wrong-length one would otherwise crash opaquely on first use.

    @override_settings(ENCRYPTION_SALT_KEYS=["00beef0000beef0000beef0000beef00"])
    def test_single_valid_key_passes(self):
        assert check_encryption_salt_keys(None) == []

    @override_settings(ENCRYPTION_SALT_KEYS=get_list("00beef0000beef0000beef0000beef00," + "a" * 32))
    def test_two_valid_keys_pass(self):
        assert check_encryption_salt_keys(None) == []

    @override_settings(ENCRYPTION_SALT_KEYS=get_list(",".join(["a" * 32, "b" * 32, "c" * 32])))
    def test_three_valid_keys_pass(self):
        assert check_encryption_salt_keys(None) == []

    @override_settings(ENCRYPTION_SALT_KEYS=["tooshort"])
    def test_short_key_is_flagged(self):
        errors = check_encryption_salt_keys(None)
        assert len(errors) == 1
        assert errors[0].id == "posthog.E004"
        assert "ENCRYPTION_SALT_KEYS[0]" in errors[0].msg
        assert "got 8" in errors[0].msg

    @override_settings(ENCRYPTION_SALT_KEYS=["a" * 33])
    def test_long_key_is_flagged(self):
        errors = check_encryption_salt_keys(None)
        assert len(errors) == 1
        assert "got 33" in errors[0].msg

    @override_settings(ENCRYPTION_SALT_KEYS=["a" * 32, "b" * 31])
    def test_reports_index_of_offending_key(self):
        errors = check_encryption_salt_keys(None)
        assert len(errors) == 1
        assert "ENCRYPTION_SALT_KEYS[1]" in errors[0].msg

    @override_settings(ENCRYPTION_SALT_KEYS=["é" * 32])
    def test_counts_bytes_not_characters(self):
        # 32 'é' is 64 bytes in UTF-8 — must be flagged, since Fernet keys are byte-sized
        errors = check_encryption_salt_keys(None)
        assert len(errors) == 1
        assert "got 64" in errors[0].msg

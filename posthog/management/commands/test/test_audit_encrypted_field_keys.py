import base64

from django.test import SimpleTestCase, override_settings

from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from posthog.management.commands.audit_encrypted_field_keys import (
    CLEAN,
    EMPTY,
    LEGACY,
    PLAINTEXT,
    UNREADABLE,
    _legacy_fernet,
    _salt_only_fernet,
    classify,
)

# ENCRYPTION_KEY and OTHER_KEY are used directly as Fernet keys, so they must be exactly 32 bytes.
# SECRET and SALT_RAW only feed PBKDF2 (password / salt), so their length is irrelevant.
SALT_RAW = "a" * 32
SECRET = "b" * 32
ENCRYPTION_KEY = "c" * 32
OTHER_KEY = "d" * 32


def _salt_fernet(raw_key: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(raw_key.encode("utf-8")))


def _secret_derived_fernet(secret_key: str, salt_key: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt_key.encode("utf-8"),
        iterations=100000,
        backend=default_backend(),
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(secret_key.encode("utf-8"))))


@override_settings(
    ENCRYPTION_SALT_KEYS=[ENCRYPTION_KEY], SECRET_KEY=SECRET, SECRET_KEY_FALLBACKS=[], SALT_KEY=[SALT_RAW]
)
class TestAuditClassify(SimpleTestCase):
    def setUp(self):
        self.salt_only = _salt_only_fernet()
        self.legacy = _legacy_fernet()

    def _enc_salt(self, plaintext="secret"):
        return _salt_fernet(ENCRYPTION_KEY).encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def _enc_legacy(self, plaintext="secret"):
        return _secret_derived_fernet(SECRET, SALT_RAW).encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def _enc_other(self, plaintext="secret"):
        return _salt_fernet(OTHER_KEY).encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def test_scalar_token_under_encryption_salt_key_is_clean(self):
        assert classify(self._enc_salt(), self.salt_only, self.legacy) == CLEAN

    def test_scalar_token_under_secret_derived_key_is_legacy(self):
        assert classify(self._enc_legacy(), self.salt_only, self.legacy) == LEGACY

    def test_token_under_unknown_key_is_unreadable(self):
        assert classify(self._enc_other(), self.salt_only, self.legacy) == UNREADABLE

    def test_non_token_string_is_plaintext(self):
        assert classify("not-encrypted-at-all", self.salt_only, self.legacy) == PLAINTEXT

    def test_empty_and_trivial_values_are_empty(self):
        for value in (None, "", "{}", "[]", "null", {}, []):
            assert classify(value, self.salt_only, self.legacy) == EMPTY, value

    def test_json_field_all_leaves_clean(self):
        raw = {"a": self._enc_salt("x"), "nested": {"b": self._enc_salt("y")}, "list": [self._enc_salt("z")]}
        assert classify(raw, self.salt_only, self.legacy) == CLEAN

    def test_json_field_with_one_legacy_leaf_is_legacy(self):
        raw = {"a": self._enc_salt("x"), "b": self._enc_legacy("y")}
        assert classify(raw, self.salt_only, self.legacy) == LEGACY

    def test_json_field_with_one_plaintext_leaf_is_plaintext(self):
        # A leaf that was never encrypted dominates — the whole row needs inspection
        raw = {"a": self._enc_salt("x"), "b": "leaked-plaintext"}
        assert classify(raw, self.salt_only, self.legacy) == PLAINTEXT

    @override_settings(SECRET_KEY="new-secret", SECRET_KEY_FALLBACKS=[SECRET], SALT_KEY=[SALT_RAW])
    def test_secret_derived_leaf_still_legacy_via_fallback(self):
        legacy = _legacy_fernet()
        assert classify(self._enc_legacy(), self.salt_only, legacy) == LEGACY


class TestAuditFernetBuilders(SimpleTestCase):
    @override_settings(ENCRYPTION_SALT_KEYS=[], SALT_KEY=[])
    def test_salt_only_fernet_is_none_when_no_keys(self):
        assert _salt_only_fernet() is None

    @override_settings(SECRET_KEY=SECRET, SECRET_KEY_FALLBACKS=[], SALT_KEY=[])
    def test_legacy_fernet_is_none_when_no_salt_keys(self):
        assert _legacy_fernet() is None

    @override_settings(SECRET_KEY=SECRET, SECRET_KEY_FALLBACKS=["fb1", "fb2"], SALT_KEY=[SALT_RAW, "salt2"])
    def test_legacy_fernet_covers_secret_key_and_all_fallbacks(self):
        legacy = _legacy_fernet()
        assert isinstance(legacy, MultiFernet)
        # 3 secret keys (secret + 2 fallbacks) x 2 salt keys = 6 derived keys; each decrypts its own ciphertext
        token = _secret_derived_fernet("fb2", "salt2").encrypt(b"x").decode("utf-8")
        assert legacy.decrypt(token.encode("utf-8")) == b"x"

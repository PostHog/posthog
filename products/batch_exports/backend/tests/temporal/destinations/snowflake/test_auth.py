import io

import paramiko
import pytest

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    InvalidPrivateKeyError,
    load_private_key,
)


class TestSnowflakeKeyPairAuth:
    def _create_key(self, passphrase: str | None = None) -> io.StringIO:
        key = paramiko.RSAKey.generate(2048)
        buffer = io.StringIO()
        key.write_private_key(buffer, password=passphrase)
        _ = buffer.seek(0)
        return buffer

    def test_load_private_key_raises_error_if_key_is_invalid(self):
        with pytest.raises(InvalidPrivateKeyError):
            load_private_key("invalid_key", None)

    def test_load_private_key_raises_error_if_incorrect_passphrase(self):
        """Test we raise the right error when passing an incorrect passphrase."""
        buffer = self._create_key("a-passphrase")

        with pytest.raises(InvalidPrivateKeyError) as exc_info:
            _ = load_private_key(buffer.read(), "another-passphrase")

        assert "incorrect passphrase" in str(exc_info.value)

    def test_load_private_key_raises_error_if_passphrase_not_empty(self):
        """Test we raise the right error when passing a passphrase to a key without one."""
        buffer = self._create_key()

        with pytest.raises(InvalidPrivateKeyError) as exc_info:
            _ = load_private_key(buffer.read(), "a-passphrase")

        assert "passphrase was given but private key is not encrypted" in str(exc_info.value)

    def test_load_private_key_raises_error_if_passphrase_missing(self):
        """Test we raise the right error when missing a passphrase to an encrypted key."""
        buffer = self._create_key("a-passphrase")

        with pytest.raises(InvalidPrivateKeyError) as exc_info:
            _ = load_private_key(buffer.read(), None)

        assert "passphrase was not given but private key is encrypted" in str(exc_info.value)

    def test_load_private_key_passes_with_empty_passphrase_and_no_encryption(self):
        """Test we succeed in loading a passphrase without encryption and an empty passphrase."""
        buffer = self._create_key()
        loaded = load_private_key(buffer.read(), "")
        assert loaded

    @pytest.mark.parametrize("passphrase", ["a-passphrase", None, ""])
    def test_load_private_key(self, passphrase: str | None):
        """Test we can load a private key.

        We treat `None` and empty string the same (no passphrase) because paramiko does
        not support passphrases smaller than 1 byte.
        """
        buffer = self._create_key(passphrase=None if passphrase is None or passphrase == "" else passphrase)
        private_key = buffer.read()

        # Just checking this doesn't fail.
        loaded = load_private_key(private_key, passphrase)
        assert loaded

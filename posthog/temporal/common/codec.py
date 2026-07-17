import base64
import typing
import collections.abc

from cryptography.fernet import Fernet, MultiFernet
from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec


class _RequiredSettings(typing.Protocol):
    """Protocol for required settings."""

    TEMPORAL_SECRET_KEY: str | bytes
    TEMPORAL_FALLBACK_SECRET_KEYS: collections.abc.Iterable[str | bytes]
    TEST: bool
    DEBUG: bool


def _load_as_bytes(raw: str | bytes, /, check_length: bool = True) -> bytes:
    if isinstance(raw, bytes):
        loaded = raw

    else:
        prefix, sep, secret = raw.partition(":")

        if sep and prefix == "hex":
            loaded = bytes.fromhex(secret)

        elif sep and prefix == "base64-urlsafe":
            loaded = base64.urlsafe_b64decode(secret)

        elif sep and prefix == "base64":
            loaded = base64.b64decode(secret, validate=True)

        else:
            # Legacy format, kept for backwards compatibility
            # TODO: Remove this branch & raise after rotating secrets
            loaded = raw.encode()

    # TODO: Also, make the check exact after removing legacy format
    if check_length and len(loaded) < 32:
        raise ValueError(f"Expected at least 32 bytes, got '{len(loaded)}'")

    return loaded


def _prepare_key(key: bytes) -> bytes:
    """Prepare an encryption key by padding or truncating it, and encoding it.

    We require a URL-safe, base64 encoded, 32 byte key.
    """
    resized_key = _resize_key(key)
    encoded_key = base64.urlsafe_b64encode(resized_key)
    return encoded_key


def _resize_key(key: bytes, size: int = 32) -> bytes:
    """Resize key to size bytes.

    Adds padding if key is too short, otherwise truncates to first 32 bytes.
    """
    padding = b"\0" * max(size - len(key), 0)
    return (padding + key)[:size]


class EncryptionCodec(PayloadCodec):
    """Handles encryption and decryption of all Temporal payloads.

    Pass an instance of this when initializing a Temporal client to ensure all inputs
    and outputs going to and from the Temporal server are encrypted.

    All encryption keys must be URL-safe, base64 encoded, 32-byte keys.

    Args:
        key: The preferred encryption key.
        fallback_keys: Any number of additional keys to be used when decrypting with
            key fails. This allows rotating keys by moving the current key to the
            fallbacks temporarily.
    """

    def __init__(self, key: bytes, fallback_keys: collections.abc.Iterable[bytes]) -> None:
        super().__init__()

        main = Fernet(key)
        fallbacks = map(Fernet, fallback_keys)
        self.fernet = MultiFernet([main, *fallbacks])

    @classmethod
    def from_settings(cls, settings: _RequiredSettings) -> typing.Self:
        """Initialize an EncryptionCodec from any settings-like object.

        Args:
            settings: Any settings-like object containing required encryption keys,
                like a Django settings module. Keys must be at least 32 bytes long, and
                will be padded to 32 bytes in TEST or DEBUG environments.

        Raises:
            ValueError: If a key with less than 32 bytes is used in non-TEST non-DEBUG
                environments.
        """
        should_check_length = not settings.TEST and not settings.DEBUG
        main_key = _prepare_key(_load_as_bytes(settings.TEMPORAL_SECRET_KEY, check_length=should_check_length))
        fallback_keys = map(
            _prepare_key,
            (
                _load_as_bytes(secret, check_length=should_check_length)
                for secret in settings.TEMPORAL_FALLBACK_SECRET_KEYS
            ),
        )

        return cls(main_key, fallback_keys)

    async def encode(self, payloads: collections.abc.Iterable[Payload]) -> list[Payload]:
        """Encrypt all payloads during encoding."""
        return [
            Payload(
                metadata={
                    "encoding": b"binary/encrypted",
                },
                data=self.encrypt(p.SerializeToString()),
            )
            for p in payloads
        ]

    async def decode(self, payloads: collections.abc.Iterable[Payload]) -> list[Payload]:
        """Decode all payloads decrypting those with expected encoding."""
        ret: list[Payload] = []
        for p in payloads:
            # Ignore ones without our expected encoding
            if p.metadata.get("encoding", b"").decode() != "binary/encrypted":
                ret.append(p)
                continue

            ret.append(Payload.FromString(self.decrypt(p.data)))
        return ret

    def encrypt(self, data: bytes) -> bytes:
        """Return data encrypted."""
        return self.fernet.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        """Return data decrypted."""
        return self.fernet.decrypt(data)

import base64
import typing
import collections.abc

from cryptography.fernet import Fernet, MultiFernet
from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec


class _RequiredSettings(typing.Protocol):
    """Protocol for required settings."""

    TEMPORAL_SECRET_KEY: str | bytes
    TEMPORAL_FALLBACK_KEYS: collections.abc.Iterable[str | bytes]
    TEST: bool
    DEBUG: bool


def _prepare_key(key: str | bytes) -> bytes:
    """Prepare an encryption key by padding or truncating it, and encoding it.

    We require a URL-safe, base64 encoded, 32 byte key.
    """
    key_bytes = key.encode() if isinstance(key, str) else key
    resized_key = _resize_key(key_bytes)
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
        if not settings.TEST and not settings.DEBUG:
            if any(len(key) < 32 for key in (settings.TEMPORAL_SECRET_KEY, *settings.TEMPORAL_FALLBACK_KEYS)):
                raise ValueError("Keys must be at least 32 bytes")

        main_key = _prepare_key(settings.TEMPORAL_SECRET_KEY)
        fallback_keys = map(_prepare_key, settings.TEMPORAL_FALLBACK_KEYS)

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

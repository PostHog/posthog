import base64
from collections.abc import Iterable

from cryptography.fernet import Fernet
from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec


class EncryptionCodec(PayloadCodec):
    """A PayloadCodec that encrypts/decrypts all Payloads.

    Args:
        settings: Django settings to obtain the SECRET_KEY to use for encryption.
    """

    def __init__(self, settings) -> None:
        super().__init__()

        # Fernet requires a URL safe, base64 encoded, 32 byte key. So, we pad the SECRET_KEY
        # if it's not long enough (like in TEST environments) or we truncate it if it's too long.
        padded_key = b"\0" * max(32 - len(settings.SECRET_KEY), 0) + settings.SECRET_KEY.encode()
        encoded_key = base64.urlsafe_b64encode(padded_key[:32])
        self.fernet = Fernet(encoded_key)

    async def encode(self, payloads: Iterable[Payload]) -> list[Payload]:
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

    async def decode(self, payloads: Iterable[Payload]) -> list[Payload]:
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

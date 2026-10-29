import re
import hmac
import base64
import hashlib
import binascii
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def encode_digest(encoding: Literal["hex", "base64", "base64url", "binary"], digest: bytes) -> str:
    if encoding == "hex":
        return digest.hex()
    elif encoding == "base64":
        return base64.b64encode(digest).decode()
    elif encoding == "base64url":
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")
    elif encoding == "binary":
        return digest.decode("latin1")


def md5(data: str | None, encoding: Literal["hex", "base64", "base64url", "binary"] = "hex") -> str | None:
    if data is None:
        return None
    # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
    digest = hashlib.md5(data.encode()).digest()

    return encode_digest(encoding, digest)


def sha256(data: str | None, encoding: Literal["hex", "base64", "base64url", "binary"] = "hex") -> str | None:
    if data is None:
        return None
    digest = hashlib.sha256(data.encode()).digest()

    return encode_digest(encoding, digest)


def sha1(data: str | None, encoding: Literal["hex", "base64", "base64url", "binary"] = "hex") -> str | None:
    if data is None:
        return None
    # SHA-1 is only here because vendors sign webhooks with it. Never pick it for new work.
    # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
    digest = hashlib.sha1(data.encode()).digest()

    return encode_digest(encoding, digest)


def _hmac_chain(data: list, digestmod: str, encoding: Literal["hex", "base64", "base64url", "binary"]) -> str:
    if len(data) < 2:
        raise ValueError("Data array must contain at least two elements.")

    hmac_obj = hmac.new(data[0].encode(), data[1].encode(), digestmod)
    for i in range(2, len(data)):
        hmac_obj = hmac.new(hmac_obj.digest(), data[i].encode(), digestmod)

    digest = hmac_obj.digest()

    return encode_digest(encoding, digest)


def sha256HmacChain(data: list, encoding: Literal["hex", "base64", "base64url", "binary"] = "hex") -> str:
    return _hmac_chain(data, "sha256", encoding)


def sha1HmacChain(data: list, encoding: Literal["hex", "base64", "base64url", "binary"] = "hex") -> str:
    return _hmac_chain(data, "sha1", encoding)


def sha256HmacBase64Key(key: str, data: str, encoding: Literal["hex", "base64", "base64url", "binary"] = "hex") -> str:
    # Svix-style webhook secrets are random bytes, which a string key would corrupt. The extra
    # padding makes the decode accept a key with or without padding, as Node does.
    key_bytes = base64.b64decode(key.strip() + "==")
    digest = hmac.new(key_bytes, data.encode(), hashlib.sha256).digest()

    return encode_digest(encoding, digest)


def _decode_verify_arg(value: str, encoding: str, expected_bytes: int) -> bytes | None:
    try:
        if encoding == "hex":
            if not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", value):
                return None
            decoded = bytes.fromhex(value)
        else:
            decoded = base64.b64decode(value + "==")
    except (ValueError, binascii.Error):
        return None
    return decoded if len(decoded) == expected_bytes else None


# Returns False for a malformed key or signature, so a bad webhook reads as unverified, not as a crash.
def ed25519Verify(message: object, signature: object, public_key: object, encoding: str = "hex") -> bool:
    if encoding not in ("hex", "base64"):
        raise ValueError(f"ed25519Verify: encoding must be 'hex' or 'base64', got '{encoding}'")
    if not isinstance(message, str) or not isinstance(signature, str) or not isinstance(public_key, str):
        return False
    signature_bytes = _decode_verify_arg(signature.strip(), encoding, 64)
    key_bytes = _decode_verify_arg(public_key.strip(), encoding, 32)
    if signature_bytes is None or key_bytes is None:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature_bytes, message.encode())
    except (InvalidSignature, ValueError):
        return False
    return True

import hmac
import base64
import hashlib
from typing import Literal


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
    digest = hashlib.md5(data.encode()).digest()

    return encode_digest(encoding, digest)


def sha256(data: str | None, encoding: Literal["hex", "base64", "base64url", "binary"] = "hex") -> str | None:
    if data is None:
        return None
    digest = hashlib.sha256(data.encode()).digest()

    return encode_digest(encoding, digest)


def sha256HmacChain(data: list, encoding: Literal["hex", "base64", "base64url", "binary"] = "hex") -> str:
    if len(data) < 2:
        raise ValueError("Data array must contain at least two elements.")

    hmac_obj = hmac.new(data[0].encode(), data[1].encode(), hashlib.sha256)
    for i in range(2, len(data)):
        hmac_obj = hmac.new(hmac_obj.digest(), data[i].encode(), hashlib.sha256)

    digest = hmac_obj.digest()

    return encode_digest(encoding, digest)

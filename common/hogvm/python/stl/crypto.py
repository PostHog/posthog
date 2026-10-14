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

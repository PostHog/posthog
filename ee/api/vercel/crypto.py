import json
import uuid
import zlib
import base64
import hashlib

from django.conf import settings
from django.core.cache import cache

from cryptography.fernet import Fernet

USED_TOKEN_CACHE_PREFIX = "vercel_token_used:"


def _get_fernet(salt: str) -> Fernet:
    key_material = f"{salt}{settings.VERCEL_CLIENT_INTEGRATION_SECRET}"
    key = base64.urlsafe_b64encode(hashlib.sha256(key_material.encode()).digest())
    return Fernet(key)


def encrypt_payload(data: dict, salt: str, jti: bool = True) -> str:
    if jti:
        data["jti"] = str(uuid.uuid4())
    payload = zlib.compress(json.dumps(data).encode())
    return _get_fernet(salt).encrypt(payload).decode()


def decrypt_payload(token: str, salt: str, ttl: int) -> dict:
    decrypted = _get_fernet(salt).decrypt(token.encode(), ttl=ttl)
    return json.loads(zlib.decompress(decrypted))


def mark_token_used(jti: str, ttl: int) -> bool:
    cache_key = f"{USED_TOKEN_CACHE_PREFIX}{jti}"
    if cache.get(cache_key):
        return False
    cache.set(cache_key, True, timeout=ttl)
    return True

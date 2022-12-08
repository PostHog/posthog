from base64 import urlsafe_b64decode as b64d
from base64 import urlsafe_b64encode as b64e

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from posthog.settings import SECRET_KEY

SECRET_BYTES = SECRET_KEY.encode()
ITERATIONS = 100_000

backend = default_backend()

"""
All based on this awesome StackOverflow answer: https://stackoverflow.com/a/55147077
"""


def _derive_key() -> bytes:
    """
    Yes, it's bad to reuse the same salt every time, but we're not using this for security.
    We're encrypting to hide the user's id when used in a URL _rather_ than store state for each user.
    """
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SECRET_BYTES, iterations=ITERATIONS, backend=backend)
    return b64e(kdf.derive(SECRET_BYTES))


def user_id_encrypt(user_id: str) -> bytes:
    key = _derive_key()
    return b64e(b"%b" % (b64d(Fernet(key).encrypt(user_id.encode())),))


def user_id_decrypt(token: bytes) -> str:
    key = _derive_key()
    decrypted = Fernet(key).decrypt(token)
    return decrypted.decode()

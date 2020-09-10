import secrets
import uuid
from collections import namedtuple
from typing import Callable, Sequence

from django.db import models


def uuid1_macless() -> uuid.UUID:
    """Time-based UUID v1 using random 48 bits rather than the real MAC address, for more randomness and security.
    
    For primary keys, this is superior to incremented integers
    (as they can reveal sensitive business information about usage volumes and patterns) and to UUID v4
    (as the complete randomness of v4 makes it less useful for indexing or possibly sorting).
    """
    return uuid.uuid1(secrets.randbits(48) | 0x010000000000)  # https://tools.ietf.org/html/rfc4122#section-4.5


class UUIDModel(models.Model):
    class Meta:
        abstract = True

    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid1_macless, editable=False)


def sane_repr(*attrs: str) -> Callable[[object], str]:
    if "id" not in attrs and "pk" not in attrs:
        attrs = ("id",) + attrs

    def _repr(self):
        pairs = (f"{attr}={repr(getattr(self, attr))}" for attr in attrs)
        return f"<{type(self).__name__} at {hex(id(self))}: {', '.join(pairs)}>"

    return _repr


def namedtuplefetchall(cursor):
    """Return all rows from a cursor as a namedtuple"""
    desc = cursor.description
    nt_result = namedtuple("Result", [col[0] for col in desc])  # type: ignore
    return [nt_result(*row) for row in cursor.fetchall()]


def generate_random_token(nbytes: int = 32) -> str:
    """Generate a securely random token.

    Random 32 bytes - default value here - is believed to be sufficiently secure for practically all purposes:
    https://docs.python.org/3/library/secrets.html#how-many-bytes-should-tokens-use
    """
    return secrets.token_urlsafe(nbytes)

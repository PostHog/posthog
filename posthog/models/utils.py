import secrets
import uuid
from collections import defaultdict, namedtuple
from time import time
from typing import Callable, Dict, Optional

from django.db import models


class UUIDT(uuid.UUID):
    """UUID (mostly) sortable by generation time.

    This doesn't adhere to any official UUID version spec, but it is superior as a primary key:
    to incremented integers (as they can reveal sensitive business information about usage volumes and patterns),
    to UUID v4 (as the complete randomness of v4 makes its indexing performance suboptimal),
    and to UUID v1 (as despite being time-based it can't be used practically for sorting by generation time).

    Order can be messed up if system clock is changed or if more than 65 536 IDs are generated per millisecond
    (that's over 5 trillion events per day), but it should be largely safe to assume that these are time-sortable.

    Anatomy:
    - 6 bytes - Unix time milliseconds unsigned integer
    - 2 bytes - autoincremented series unsigned integer (per millisecond, rolls over to 0 after reaching 65 535 UUIDs in one ms)
    - 8 bytes - securely random gibberish

    Loosely based on Segment's KSUID (https://github.com/segmentio/ksuid) and on Twitter's snowflake ID
    (https://blog.twitter.com/engineering/en_us/a/2010/announcing-snowflake.html).
    """

    current_series_per_ms: Dict[int, int] = defaultdict(int)

    def __init__(self, unix_time_ms: Optional[int] = None) -> None:
        if unix_time_ms is None:
            unix_time_ms = int(time() * 1000)
        time_component = unix_time_ms.to_bytes(6, "big", signed=False)  # 48 bits for time, WILL FAIL in 10 895 CE
        series_component = self.get_series(unix_time_ms).to_bytes(2, "big", signed=False)  # 16 bits for series
        random_component = secrets.token_bytes(8)  # 64 bits for random gibberish
        bytes = time_component + series_component + random_component
        assert len(bytes) == 16
        super().__init__(bytes=bytes)

    @classmethod
    def get_series(cls, unix_time_ms: int) -> int:
        """Get per-millisecond series integer in range [0-65536)."""
        series = cls.current_series_per_ms[unix_time_ms]
        if len(cls.current_series_per_ms) > 10_000:  # Clear class dict periodically
            cls.current_series_per_ms.clear()
            cls.current_series_per_ms[unix_time_ms] = series
        cls.current_series_per_ms[unix_time_ms] += 1
        cls.current_series_per_ms[unix_time_ms] %= 65_536
        return series


class UUIDModel(models.Model):
    class Meta:
        abstract = True

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)


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


class Percentile(models.Aggregate):
    template = "percentile_disc(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)"

    def __init__(self, percentile, expression, **extra):
        super().__init__(expression, percentile=percentile, **extra)

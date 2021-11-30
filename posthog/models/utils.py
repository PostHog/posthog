import random
import secrets
import string
import uuid
from collections import defaultdict, namedtuple
from time import time
from typing import Any, Callable, Dict, Optional, TypeVar

from django.db import IntegrityError, models, transaction
from django.utils.text import slugify

from posthog.constants import MAX_SLUG_LENGTH

T = TypeVar("T")

BASE62 = string.digits + string.ascii_letters  # All lowercase ASCII letters + all uppercase ASCII letters + digits


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

    def __init__(self, unix_time_ms: Optional[int] = None, uuid_str: Optional[str] = None) -> None:
        if uuid_str and self.is_valid_uuid(uuid_str):
            super().__init__(uuid_str)
            return

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

    @classmethod
    def is_valid_uuid(cls, candidate: Any) -> bool:
        if type(candidate) != str:
            return False
        hex = candidate.replace("urn:", "").replace("uuid:", "")
        hex = hex.strip("{}").replace("-", "")
        if len(hex) != 32:
            return False
        return 0 <= int(hex, 16) < 1 << 128


class UUIDModel(models.Model):
    """Base Django Model with default autoincremented ID field replaced with UUIDT."""

    class Meta:
        abstract = True

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)


class UUIDClassicModel(models.Model):
    """Base Django Model with default autoincremented ID field kept and a UUIDT field added."""

    class Meta:
        abstract = True

    uuid: models.UUIDField = models.UUIDField(unique=True, default=UUIDT, editable=False)


def sane_repr(*attrs: str, include_id=True) -> Callable[[object], str]:
    if "id" not in attrs and "pk" not in attrs and include_id:
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
    return int_to_base(secrets.randbits(nbytes * 8), 62)


def generate_random_token_project() -> str:
    return "phc_" + generate_random_token()  # "c" standing for "client"


def generate_random_token_personal() -> str:
    return "phx_" + generate_random_token()  # "x" standing for nothing in particular


def int_to_base(number: int, base: int) -> str:
    if base > 62:
        raise ValueError("Cannot convert integer to base above 62")
    alphabet = BASE62[:base]
    if number < 0:
        return "-" + int_to_base(-number, base)
    value = ""
    while number != 0:
        number, index = divmod(number, len(alphabet))
        value = alphabet[index] + value
    return value or "0"


class Percentile(models.Aggregate):
    template = "percentile_disc(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)"

    def __init__(self, percentile, expression, **extra):
        super().__init__(expression, percentile=percentile, **extra)


class LowercaseSlugField(models.SlugField):
    def get_prep_value(self, value: Optional[str]) -> Optional[str]:
        """Return model value formatted for use as a parameter in a query."""
        prep_value = super().get_prep_value(value)
        return prep_value.lower() if prep_value else prep_value


def generate_random_short_suffix():
    """Return a 4 letter suffix made up random ASCII letters, useful for disambiguation of duplicates."""
    return "".join(random.choice(string.ascii_letters) for _ in range(4))


def create_with_slug(create_func: Callable[..., T], default_slug: str = "", *args, **kwargs) -> T:
    """Run model manager create function, making sure that the model is saved with a valid autogenerated slug field."""
    slugified_name = slugify(kwargs["name"])[:MAX_SLUG_LENGTH] if "name" in kwargs else default_slug
    for retry_i in range(10):
        # This retry loop handles possible duplicates by appending `-\d` to the slug in case of an IntegrityError
        if not retry_i:
            kwargs["slug"] = slugified_name
        else:
            kwargs["slug"] = f"{slugified_name[: MAX_SLUG_LENGTH - 5]}-{generate_random_short_suffix()}"
        try:
            with transaction.atomic():
                return create_func(*args, **kwargs)
        except IntegrityError:
            continue
    raise Exception("Could not create a model instance with slug in 10 tries!")

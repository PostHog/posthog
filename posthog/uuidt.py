import uuid
import secrets
import datetime
from collections import defaultdict
from time import time, time_ns
from typing import TYPE_CHECKING, Any, Optional, Union

# Django-free UUID helpers. Kept out of posthog.models.utils (which imports the Django ORM at
# module level) so the HogQL engine can use them without booting Django. posthog.models.utils
# re-exports these names for existing callers.

if TYPE_CHECKING:
    from random import Random


class UUIDT(uuid.UUID):
    """
    Deprecated, you probably want to use UUIDv7 instead. As of May 2024 the latest RFC with the UUIDv7 spec is at
    Proposed Standard (see RFC9562 https://www.rfc-editor.org/rfc/rfc9562#name-uuid-version-7). This class was written
    well before that, is still in use in PostHog, but should not be used for new columns / models / features / etc.

    UUID (mostly) sortable by generation time.

    This doesn't adhere to any official UUID version spec, but it is superior as a primary key:
    to incremented integers (as they can reveal sensitive business information about usage volumes and patterns),
    to UUID v4 (as the complete randomness of v4 makes its indexing performance suboptimal),
    and to UUID v1 (as despite being time-based it can't be used practically for sorting by generation time).

    Order can be messed up if system clock is changed or if more than 65 536 IDs are generated per millisecond
    (that's over 5 trillion events per day), but it should be largely safe to assume that these are time-sortable.

    Anatomy:
    - 6 bytes - Unix time milliseconds unsigned integer
    - 2 bytes - autoincremented series unsigned integer (per millisecond, rolls over to 0 after reaching 65 535 UUIDs in one ms)
    - 8 bytes - securely random gibberish

    Loosely based on Segment's KSUID (https://github.com/segmentio/ksuid) and on Twitter's snowflake ID
    (https://blog.twitter.com/engineering/en_us/a/2010/announcing-snowflake.html).
    """

    current_series_per_ms: dict[int, int] = defaultdict(int)

    def __init__(
        self,
        unix_time_ms: Optional[int] = None,
        uuid_str: Optional[str] = None,
        *,
        seeded_random: Optional["Random"] = None,
    ) -> None:
        if uuid_str and self.is_valid_uuid(uuid_str):
            super().__init__(uuid_str)
            return

        if unix_time_ms is None:
            unix_time_ms = int(time() * 1000)
        time_component = unix_time_ms.to_bytes(6, "big", signed=False)  # 48 bits for time, WILL FAIL in 10 895 CE
        series_component = self.get_series(unix_time_ms).to_bytes(2, "big", signed=False)  # 16 bits for series
        if seeded_random is not None:
            random_component = bytes(seeded_random.getrandbits(8) for _ in range(8))  # 64 bits for random gibberish
        else:
            random_component = secrets.token_bytes(8)  # 64 bits for random gibberish
        input_bytes = time_component + series_component + random_component
        assert len(input_bytes) == 16
        super().__init__(bytes=input_bytes)

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
        if not isinstance(candidate, str):
            return False
        hex_str = candidate.replace("urn:", "").replace("uuid:", "")
        hex_str = hex_str.strip("{}").replace("-", "")
        if len(hex_str) != 32:
            return False
        try:
            return 0 <= int(hex_str, 16) < (1 << 128)
        except ValueError:
            return False


# Delete this when we can use the version from the stdlib directly, see https://github.com/python/cpython/issues/102461
def uuid7(unix_ms_time: Optional[Union[int, str]] = None, random: Optional[Union["Random", int]] = None) -> uuid.UUID:
    # timestamp part
    unix_ms_time_int: int
    if isinstance(unix_ms_time, str):
        # parse the ISO format string, use the timestamp from that
        date = datetime.datetime.fromisoformat(unix_ms_time)
        unix_ms_time_int = int(date.timestamp() * 1000)
    elif unix_ms_time is None:
        # use the current system time
        unix_ms_time_int = time_ns() // (10**6)
    else:
        # use the provided timestamp directly
        unix_ms_time_int = unix_ms_time

    # random part
    if isinstance(random, int):
        # use the integer directly as the random component
        rand_a = random & 0x0FFF
        rand_b = random >> 12 & 0x03FFFFFFFFFFFFFFF
    elif random is not None:
        # use the provided random generator
        rand_a = random.getrandbits(12)
        rand_b = random.getrandbits(56)
    else:
        # use the system random generator
        rand_bytes = int.from_bytes(secrets.token_bytes(10), byteorder="little")
        rand_a = rand_bytes & 0x0FFF
        rand_b = (rand_bytes >> 12) & 0x03FFFFFFFFFFFFFFF

    # fixed constants
    ver = 7
    var = 0b10

    # construct the UUID int
    uuid_int = (unix_ms_time_int & 0x0FFFFFFFFFFFF) << 80
    uuid_int |= ver << 76
    uuid_int |= rand_a << 64
    uuid_int |= var << 62
    uuid_int |= rand_b
    return uuid.UUID(int=uuid_int)

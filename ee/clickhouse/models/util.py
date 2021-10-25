import json
from enum import Enum, auto
from typing import Optional, Union

import pytz
from dateutil.parser import isoparse
from django.utils import timezone


class PersonPropertiesMode(Enum):
    USING_SUBQUERY = auto()
    USING_PERSON_PROPERTIES_COLUMN = auto()
    # Used when person join handles these filters
    EXCLUDE = auto()


def is_json(val):
    if isinstance(val, int):
        return False

    try:
        int(val)
        return False
    except:
        pass
    try:
        json.loads(val)
    except (ValueError, TypeError):
        return False
    return True


def cast_timestamp_or_now(timestamp: Optional[Union[timezone.datetime, str]]) -> str:
    if not timestamp:
        timestamp = timezone.now()

    # clickhouse specific formatting
    if isinstance(timestamp, str):
        timestamp = isoparse(timestamp)
    else:
        timestamp = timestamp.astimezone(pytz.utc)

    return timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")

from datetime import datetime, timedelta
from typing import Optional, Tuple

from posthog.models.filter import Filter


def parse_timestamps(filter: Filter) -> Tuple[Optional[str], Optional[str]]:
    date_from = None
    date_to = None

    if filter.date_from:
        date_from = "and timestamp > '{}'".format(filter.date_from.strftime("%Y-%m-%d 00:00:00"))

    if filter.date_to:
        _date_to = filter.date_to + timedelta(days=1)
    else:
        _date_to = datetime.now() + timedelta(days=1)

    date_to = "and timestamp < '{}'".format(_date_to.strftime("%Y-%m-%d 00:00:00"))

    return date_from, date_to

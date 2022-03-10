from datetime import datetime
from typing import Tuple

from django.utils import timezone

from ee.clickhouse.sql.events import GET_EARLIEST_TIMESTAMP_SQL
from posthog.client import sync_execute
from posthog.models.event import DEFAULT_EARLIEST_TIME_DELTA
from posthog.types import FilterType

EARLIEST_TIMESTAMP = "2015-01-01"


def parse_timestamps(filter: FilterType, team_id: int, table: str = "") -> Tuple[str, str, dict]:
    date_from = None
    date_to = None
    params = {}
    if filter.date_from:

        date_from = f"AND {table}timestamp >= %(date_from)s"
        params.update({"date_from": format_ch_timestamp(filter.date_from, filter)})
    else:
        try:
            earliest_date = get_earliest_timestamp(team_id)
        except IndexError:
            date_from = ""
        else:
            date_from = f"AND {table}timestamp >= %(date_from)s"
            params.update({"date_from": format_ch_timestamp(earliest_date, filter)})

    _date_to = filter.date_to

    date_to = f"AND {table}timestamp <= %(date_to)s"
    params.update({"date_to": format_ch_timestamp(_date_to, filter, " 23:59:59")})

    return date_from or "", date_to or "", params


def format_ch_timestamp(timestamp: datetime, filter, default_hour_min: str = " 00:00:00"):
    is_hour = (
        (filter.interval and filter.interval.lower() == "hour")
        or (filter._date_from == "-24h")
        or (filter._date_from == "-48h")
    )
    return timestamp.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if is_hour else default_hour_min))


def get_earliest_timestamp(team_id: int) -> datetime:
    results = sync_execute(GET_EARLIEST_TIMESTAMP_SQL, {"team_id": team_id, "earliest_timestamp": EARLIEST_TIMESTAMP})
    if len(results) > 0:
        return results[0][0]
    else:
        return timezone.now() - DEFAULT_EARLIEST_TIME_DELTA

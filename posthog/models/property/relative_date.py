import re
import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from dateutil import parser
from dateutil.relativedelta import relativedelta

from posthog.models.property.property import ValueT


def convert_to_datetime_aware(date_obj: datetime.datetime) -> datetime.datetime:
    if date_obj.tzinfo is None:
        date_obj = date_obj.replace(tzinfo=datetime.UTC)
    return date_obj


def determine_parsed_date_for_property_matching(value: ValueT) -> datetime.datetime | None:
    # This parses the filter value we compare against. The range of possible values is limited by our UI.
    parsed_date = None
    try:
        parsed_date = relative_date_parse_for_feature_flag_matching(str(value))

        if not parsed_date:
            parsed_date = parser.parse(str(value))
            parsed_date = convert_to_datetime_aware(parsed_date)
    except Exception:
        return None

    return parsed_date


# Note: Any changes to this function need to be reflected in the rust version
# rust/feature-flags/src/properties/relative_date.rs
def relative_date_parse_for_feature_flag_matching(value: str) -> Optional[datetime.datetime]:
    regex = r"^-?(?P<number>[0-9]+)(?P<interval>[a-z])$"
    match = re.search(regex, value)
    parsed_dt = datetime.datetime.now(tz=ZoneInfo("UTC"))
    if match:
        number = int(match.group("number"))

        if number >= 10_000:
            # Guard against overflow, disallow numbers greater than 10_000
            return None

        interval = match.group("interval")
        if interval == "h":
            parsed_dt = parsed_dt - relativedelta(hours=number)
        elif interval == "d":
            parsed_dt = parsed_dt - relativedelta(days=number)
        elif interval == "w":
            parsed_dt = parsed_dt - relativedelta(weeks=number)
        elif interval == "m":
            parsed_dt = parsed_dt - relativedelta(months=number)
        elif interval == "y":
            parsed_dt = parsed_dt - relativedelta(years=number)
        else:
            return None

        return parsed_dt
    else:
        return None

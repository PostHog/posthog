from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta, MO, SU

from posthog.models.team import WeekStartDay
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


def _get_week_boundaries(input_date: date, week_start_day: WeekStartDay) -> tuple[date, date]:
    """
    Get the start and end dates of the week for a given date, considering the week start day.

    :param input_date: The date for which to find the week boundaries.
    :param week_start_day: The day that the week starts on (e.g., Sunday or Monday).
    :return: A tuple containing the start and end dates of the week.
    """
    if week_start_day == WeekStartDay.MONDAY:
        week_start = MO
    else:
        week_start = SU

    start_date = input_date + relativedelta(weekday=week_start(-1))
    end_date = start_date + timedelta(days=6)

    return start_date, end_date


def _format_date_range(start_date: date, end_date: date) -> str:
    """
    Format the date range based on the start and end dates, considering the query date range.

    :param start_date: The start date of the range.
    :param end_date: The end date of the range.
    :return: A formatted string representing the date range.
    """
    if start_date == end_date:
        return start_date.strftime("%-d-%b-%Y")

    if start_date.year != end_date.year:
        return f"{start_date.strftime('%-d-%b-%Y')} – {end_date.strftime('%-d-%b-%Y')}"
    if start_date.month != end_date.month:
        return f"{start_date.strftime('%-d-%b')} – {end_date.strftime('%-d-%b')}"

    return f"{start_date.strftime('%-d')}–{end_date.strftime('%-d %b')}"


def _format_week_label(input_date: date, query_date_range: QueryDateRange, week_start_day: WeekStartDay) -> str:
    """
    Format a date to be used as a label for a week.

    :param input_date: The date in the week to format.
    :param query_date_range: The query date range containing the date_from and date_to.
    :param week_start_day: The day that the week starts on (e.g., Sunday or Monday).
    :return: A formatted string representing the week label.
    """
    start_date, end_date = _get_week_boundaries(input_date, week_start_day)

    # Ensure the start and end dates are within the query date range
    start_date = max(start_date, query_date_range.date_from().date())
    end_date = min(end_date, query_date_range.date_to().date())

    # Ensure the end date is not before the start date
    end_date = max(end_date, start_date)

    return _format_date_range(start_date, end_date)


def format_label_date(
    input_date: datetime, query_date_range: QueryDateRange, week_start_day=WeekStartDay.SUNDAY
) -> str:
    """
    Format a date to be used as a label.

    :param input_date: The date to format.
    :param query_date_range: The query date range containing the date_from and date_to.
    :param week_start_day: The day that the week starts on (e.g., Sunday or Monday).
    :return: A formatted string representing the date label.
    """
    interval = query_date_range.interval_name

    if interval == "week":
        return _format_week_label(
            input_date.date() if isinstance(input_date, datetime) else input_date, query_date_range, week_start_day
        )

    date_formats = {
        "day": "%-d-%b-%Y",
        "minute": "%-d-%b %H:%M",
        "hour": "%-d-%b %H:%M",
        "month": "%b %Y",
    }
    labels_format = date_formats.get(interval, date_formats["day"])

    return input_date.strftime(labels_format)

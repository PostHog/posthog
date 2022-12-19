from datetime import datetime, timedelta


def end_of_day(reference_date: datetime):
    return datetime(
        year=reference_date.year, month=reference_date.month, day=reference_date.day, tzinfo=reference_date.tzinfo
    ) + timedelta(days=1, microseconds=-1)


def start_of_day(reference_date: datetime):
    return datetime(
        year=reference_date.year, month=reference_date.month, day=reference_date.day, tzinfo=reference_date.tzinfo
    )

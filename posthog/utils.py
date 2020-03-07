from dateutil.relativedelta import relativedelta
from django.utils.timezone import now

import datetime
import re

def relative_date_parse(input: str) -> datetime.date:
    try:
        return datetime.datetime.strptime(input, '%Y-%m-%d').date()
    except ValueError:
        pass

    regex = r"\-?(?P<number>[0-9]+)?(?P<type>[a-z])(?P<position>Start|End)?"
    match = re.search(regex, input)
    date = now()
    if not match:
        return date
    if match.group('type') == 'd':
        if match.group('number'):
            date = date - relativedelta(days=int(match.group('number')))
    elif match.group('type') == 'm':
        if match.group('number'):
            date = date - relativedelta(months=int(match.group('number')))
        if match.group('position') == 'Start':
            date = date - relativedelta(day=1)
        if match.group('position') == 'End':
            date = date - relativedelta(day=31)
    elif match.group('type') == 'y':
        if match.group('number'):
            date = date - relativedelta(years=int(match.group('number')))
        if match.group('position') == 'Start':
            date = date - relativedelta(month=1, day=1)
        if match.group('position') == 'End':
            date = date - relativedelta(month=12, day=31)
    return date.date()
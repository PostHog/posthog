from rest_framework.exceptions import ValidationError
from posthog.schema import ConversionWindowIntervalUnit


def interval_unit_to_sql(unit: ConversionWindowIntervalUnit) -> str:
    if unit == "second":
        return "toIntervalSecond"
    elif unit == "minute":
        return "toIntervalMinute"
    elif unit == "hour":
        return "toIntervalHour"
    elif unit == "day":
        return "toIntervalDay"
    elif unit == "week":
        return "toIntervalWeek"
    elif unit == "month":
        return "toInvervalMonth"
    else:
        raise ValidationError(f"{unit} not supported")

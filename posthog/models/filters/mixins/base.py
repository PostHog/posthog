from typing import Dict, Literal

BreakdownType = Literal["event", "person", "cohort"]
IntervalType = Literal["minute", "hour", "day", "week", "month"]


class BaseParamMixin:
    _data: Dict

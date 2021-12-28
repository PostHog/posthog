from typing import Dict, Literal

BreakdownType = Literal["event", "person", "cohort", "group"]
IntervalType = Literal["hour", "day", "week", "month"]
FunnelWindowIntervalType = Literal["minute", "hour", "day", "week", "month"]


class BaseParamMixin:
    _data: Dict

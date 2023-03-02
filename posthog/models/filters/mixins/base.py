from typing import Dict, Literal

BreakdownType = Literal["event", "person", "cohort", "group", "session", "hogql"]
IntervalType = Literal["hour", "day", "week", "month"]
FunnelWindowIntervalType = Literal["second", "minute", "hour", "day", "week", "month"]


class BaseParamMixin:
    _data: Dict

from posthog.dataclasses import frozen


@frozen
class Metric:
    name: str
    values: list[float]
    dates: list[str]
    current: float | None
    change: float | None
    message: str
    unit: str = ""


@frozen
class Money:
    allocated_cents: int
    spent_cents: int
    reserved_cents: int
    available_cents: int

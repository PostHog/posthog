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
class MeasureOption:
    insight: str
    name: str
    source: str
    why: str
    definition: str
    current: float | None
    unit: str
    wait_days: int
    test_days: int | None
    values: list[float]
    dates: list[str]


@frozen
class MeasureSearch:
    options: list[MeasureOption]
    draft: str


@frozen
class GuardrailOption:
    insight: str
    name: str
    definition: str
    direction: str


@frozen
class Money:
    allocated_cents: int
    spent_cents: int
    reserved_cents: int
    available_cents: int

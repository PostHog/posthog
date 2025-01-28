from enum import Enum
from typing import TypedDict, NotRequired


class ExperimentMetricType(Enum):
    COUNT = "count"
    CONTINUOUS = "continuous"
    FUNNEL = "funnel"


class ExperimentVariantQueryResult(TypedDict):
    num_entities: int
    sum_value: float
    sum_of_squares: float
    variant_name: NotRequired[str]


class ExperimentQueryResult(TypedDict):
    variants: dict[str, ExperimentVariantQueryResult]

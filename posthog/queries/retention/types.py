from typing import NamedTuple, Union

BreakdownValues = tuple[Union[str, int], ...]
CohortKey = NamedTuple("CohortKey", (("breakdown_values", BreakdownValues), ("period", int)))

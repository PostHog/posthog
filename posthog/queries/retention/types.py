from typing import NamedTuple, Tuple, Union

BreakdownValues = Tuple[Union[str, int], ...]
CohortKey = NamedTuple("CohortKey", (("breakdown_values", BreakdownValues), ("period", int)))

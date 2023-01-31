import itertools
from dataclasses import dataclass
from functools import cached_property
from typing import Dict, Sequence, Tuple, Union, cast

ParamValueType = Union[str, int, float, None]
ParamsType = Dict[str, ParamValueType]
QueryFragmentLike = Union["QueryFragment", str]

unique_sequence = itertools.count()


@dataclass
class UniqueParamName:
    name: str

    @cached_property
    def unique_name(self):
        return f"{self.name}_{next(unique_sequence)}"


class QueryFragment:
    sql: str
    params: ParamsType = {}
    _params: Dict[Union[str, UniqueParamName], ParamValueType]

    def __init__(self, sql: Union[str, "QueryFragment", Tuple[Union[str, UniqueParamName], ParamsType]], params={}):
        if isinstance(sql, str):
            self.sql = sql
            self._params = params
        elif isinstance(sql, QueryFragment):
            self.sql = sql.sql
            self._params = sql.params
        else:
            self.sql, self._params = sql

        self._update_sql_with_unique_param_names()

    def format(self, **fragments: QueryFragmentLike) -> "QueryFragment":
        new_params = {**self.params}
        for fragment in fragments.values():
            if isinstance(fragment, QueryFragment):
                new_params.update(fragment.params)

        return QueryFragment(
            self.sql.format(**{key: _get_sql(fragment) for key, fragment in fragments.items()}), new_params
        )

    @staticmethod
    def join(by: str, fragments: Sequence[QueryFragmentLike]) -> "QueryFragment":
        indexed = {str(key): fragment for key, fragment in enumerate(fragments)}
        unformatted_sql = by.join("{" + key + "}" for key in indexed.keys())
        return QueryFragment(unformatted_sql).format(**indexed)

    def _update_sql_with_unique_param_names(self):
        unique_param_names = [key for key in self._params if isinstance(key, UniqueParamName)]

        if len(unique_param_names) > 0:
            self.sql = self.sql.format(**{key.name: key.unique_name for key in unique_param_names})
            self.params = {
                (key.unique_name if isinstance(key, UniqueParamName) else key): value
                for key, value in self._params.items()
            }
        else:
            self.params = cast(ParamsType, self._params)


QF = QueryFragment


def reset_unique_sequence():
    global unique_sequence
    unique_sequence = itertools.count()


def _get_sql(fragment: QueryFragmentLike) -> str:
    if isinstance(fragment, QueryFragment):
        return fragment.sql
    else:
        return fragment

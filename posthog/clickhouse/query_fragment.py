import itertools
import re
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Dict, List, Mapping, Sequence, Tuple, Union

ParamValueType = Union[str, int, float, None, List]
QueryFragmentLike = Union["QueryFragment", str]

unique_sequence = itertools.count()


@dataclass(frozen=True)
class Param:
    value: ParamValueType


@dataclass
class QueryFragment:
    sql: str
    params: Dict[str, Param]

    def __init__(
        self,
        sql: Union[str, "QueryFragment"],
        params_and_fragments: Mapping[str, Union["Param", "QueryFragment"]] = {},
        **kwargs: Union["Param", "QueryFragment"],
    ):
        if len(kwargs) > 0 and len(params_and_fragments) > 0:
            raise ValueError("Cannot pass params as both kwargs and via positioned arguments")

        params_and_fragments = params_and_fragments if len(params_and_fragments) > 0 else kwargs
        if isinstance(sql, str):
            self.sql = sql
            self._params = params_and_fragments
        elif isinstance(sql, QueryFragment):
            self.sql = sql.sql
            self._params = sql.params

            if len(params_and_fragments) > 0:
                raise ValueError("Cannot pass both a QueryFragment object and params to a new QueryFragment")

        self._update_sql()

    @property
    def query_params(self):
        "Returns params in format clickhouse expects (removing Param wrapping)"
        return {key: prop.value for key, prop in self.params.items()}

    @staticmethod
    def from_tuple(pair: Tuple[str, Any]) -> "QueryFragment":
        sql, params = pair
        return QueryFragment(sql, {key: Param(value) for key, value in params.items()})

    @staticmethod
    def join(by: str, fragments: Sequence[QueryFragmentLike]) -> "QueryFragment":
        fragment_params = {f"k{key}": QueryFragment(fragment) for key, fragment in enumerate(fragments)}
        unformatted_sql = by.join("{" + key + "}" for key in fragment_params.keys())
        return QueryFragment(unformatted_sql, fragment_params)

    def _update_sql(self):
        self.params = {}
        format_kwargs = {}
        for key, value in self._params.items():
            if isinstance(key, UniqueName):
                if isinstance(value, QueryFragment):
                    raise ValueError("Cannot combine UniqueName and QueryFragments")

                self.sql = re.sub(f"\\b{re.escape(key.name)}\\b", key.unique_name, self.sql)
                self.params[key.unique_name] = value
            elif isinstance(value, QueryFragment):
                format_kwargs[key] = value.sql
                self.params.update(value.params)
            else:
                if not isinstance(value, Param):
                    raise ValueError("QueryFragment parameters should be either QueryFragment or Param objects")

                self.params[key] = value

        if len(format_kwargs) > 0:
            self.sql = self.sql.format(**format_kwargs)

    def __repr__(self):
        return f"QueryFragment({repr(self.sql)}, {repr(self.params)})"


@dataclass(frozen=True)
class UniqueName(str):
    # :CONVENTION: Prefix these variable names with __ to avoid collisions in sql.
    name: str

    @cached_property
    def unique_name(self):
        return f"{self.name}_{next(unique_sequence)}"


def reset_unique_sequence():
    global unique_sequence
    unique_sequence = itertools.count()

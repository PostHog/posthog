from dataclasses import dataclass
from typing import Dict, Sequence, Tuple, Union

ParamType = Union[str, int, float, None]
ParamsType = Dict[str, ParamType]
QueryFragmentLike = Union["QueryFragment", str]


@dataclass
class QueryFragment:
    sql: str
    params: ParamsType = {}

    def __init__(self, sql: Union[str, "QueryFragment", Tuple[str, ParamsType]], params={}):
        if isinstance(sql, str):
            self.sql = sql
            self.params = params
        elif isinstance(sql, QueryFragment):
            self.sql = sql.sql
            self.params = sql.params
        else:
            self.sql, self.params = sql

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


QF = QueryFragment


def _get_sql(fragment: QueryFragmentLike) -> str:
    if isinstance(fragment, QueryFragment):
        return fragment.sql
    else:
        return fragment

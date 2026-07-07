from __future__ import annotations

import re
from pathlib import Path

_TRAINING_QUERY_PATH = Path(__file__).parent / "fixtures" / "training_feature_query.sql"
_AS_ALIAS_RE = re.compile(r"\bAS\s+(\w+)\b", re.IGNORECASE)
_PASSTHROUGH_COL_RE = re.compile(r"^f\.(\w+)$", re.IGNORECASE)


def load_training_query_sql() -> str:
    return _TRAINING_QUERY_PATH.read_text()


def _balanced_cte_body(sql: str, cte_name: str) -> str:
    marker = f"{cte_name} AS ("
    start = sql.index(marker) + len(marker)
    depth = 1
    index = start
    while index < len(sql) and depth > 0:
        char = sql[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        index += 1
    return sql[start : index - 1]


def select_list_body(sql_fragment: str) -> str:
    upper = sql_fragment.upper()
    select_index = upper.find("SELECT")
    if select_index < 0:
        raise ValueError("Could not locate SELECT in SQL fragment")
    from_index = upper.find("FROM", select_index + len("SELECT"))
    if from_index < 0:
        raise ValueError("Could not locate FROM in SQL fragment")
    return sql_fragment[select_index + len("SELECT") : from_index]


def _split_select_items(body: str) -> tuple[str, ...]:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
        else:
            current.append(char)
    item = "".join(current).strip()
    if item:
        items.append(item)
    return tuple(items)


def _alias_from_select_item(item: str) -> str | None:
    as_match = _AS_ALIAS_RE.search(item)
    if as_match:
        return as_match.group(1)
    passthrough_match = _PASSTHROUGH_COL_RE.match(item.strip())
    if passthrough_match:
        return passthrough_match.group(1)
    return None


def feature_aliases_from_select_body(body: str) -> tuple[str, ...]:
    return tuple(alias for item in _split_select_items(body) if (alias := _alias_from_select_item(item)) is not None)


def training_aggregated_stat_aliases() -> tuple[str, ...]:
    sql = load_training_query_sql()
    cte_body = _balanced_cte_body(sql, "aggregated_sufficient_statistics")
    return feature_aliases_from_feature_select(select_list_body(cte_body))


def training_derived_feature_aliases() -> tuple[str, ...]:
    sql = load_training_query_sql()
    from_marker = "FROM aggregated_sufficient_statistics f"
    from_index = sql.index(from_marker)
    select_index = sql.rfind("SELECT", 0, from_index)
    if select_index < 0:
        raise AssertionError("Could not locate training query final SELECT")
    body = sql[select_index + len("SELECT") : from_index]
    return feature_aliases_from_feature_select(body)


def feature_aliases_from_feature_select(body: str) -> tuple[str, ...]:
    return tuple(alias for alias in feature_aliases_from_select_body(body) if alias not in {"session_id", "team_id"})

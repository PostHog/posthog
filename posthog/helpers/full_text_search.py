import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal, cast

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models.expressions import CombinedExpression

UNSAFE_CHARACTERS = r"[\'&|!<>():]"
"""Characters unsafe in a `tsquery`."""


def process_query(query: str) -> str | None:
    """
    Converts a query string into a to_tsquery compatible string, where
    the last word is a prefix match. This allows searching as you type.

    Example: "My search qu" becomes "My & search & qu:*"
    """
    query = re.sub(UNSAFE_CHARACTERS, " ", query).strip()
    query = re.sub(r"\s+", " & ", query)  # combine words with &
    if len(query) == 0:
        return None
    query += ":*"  # prefix match last word
    return query


def build_search_vector(
    search_fields: dict[str, Literal["A", "B", "C"]], config: str | None = None
) -> CombinedExpression:
    """
    Builds a search vector from a dict, whereby the key is the search field and the value
    is the Postgres weight e.g. `{"name": "A", "description": "C"}`.
    """
    search_vectors = [SearchVector(key, weight=value, config=config) for key, value in search_fields.items()]
    if not search_vectors:
        raise ValueError("search_fields cannot be empty")
    vector = cast(CombinedExpression, search_vectors[0])
    for search_vector in search_vectors[1:]:
        vector = cast(CombinedExpression, vector + search_vector)
    return vector


def build_rank(
    search_fields: dict[str, Literal["A", "B", "C"]], search_query: str, config: str | None = None
) -> SearchRank | None:
    """
    Builds a search rank where search fields are weighted according to the configuration and
    the search query gets processed to allow searching as you type.

    Returns `None` for empty search (after removing unsafe characters and stop words).
    """
    vector = build_search_vector(search_fields, config=config)
    search = process_query(search_query)
    if search is None:
        return None
    query = SearchQuery(search, config=config, search_type="raw")
    return SearchRank(vector, query)


def to_search_results(
    rows: Iterable[Mapping[str, Any]],
    *,
    entity_type: str,
    ranked: bool,
    access_levels: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """
    Shapes rows that carry `id`, `name` and `description`, plus `rank` when `ranked`, into the
    result dicts core search returns. `access_levels`, keyed by the id as a string, adds
    `user_access_level` to each result; `None` leaves the key out.
    """
    results: list[dict[str, Any]] = []
    for row in rows:
        result: dict[str, Any] = {
            "type": entity_type,
            "result_id": str(row["id"]),
            "extra_fields": {"name": row["name"], "description": row["description"]},
        }
        if ranked:
            result["rank"] = row["rank"]
        if access_levels is not None:
            result["user_access_level"] = access_levels.get(str(row["id"]))
        results.append(result)
    return results

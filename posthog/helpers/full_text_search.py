import re
from typing import Literal, cast

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models.expressions import CombinedExpression

UNSAFE_CHARACTERS = r"[\'&|!<>():]"
"""Characters unsafe in a `tsquery`."""


def process_query(query: str, search_type: Literal["and", "or"] = "and") -> str | None:
    """
    Converts a query string into a to_tsquery compatible string, where every word is a
    prefix match. This allows searching as you type, and keeps earlier words matchable
    even though the user is still typing the last one.

    `search_type="or"` joins words with `|` instead of `&` — a looser recall fallback for
    when the strict AND match returns nothing (e.g. one stray or slightly-off word).

    Example: "My search qu" becomes "My:* & search:* & qu:*" (AND) or
    "My:* | search:* | qu:*" (OR)
    """
    query = re.sub(UNSAFE_CHARACTERS, " ", query).strip()
    words = query.split()
    if not words:
        return None
    joiner = " & " if search_type == "and" else " | "
    return joiner.join(f"{word}:*" for word in words)


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
    search_fields: dict[str, Literal["A", "B", "C"]],
    search_query: str,
    config: str | None = None,
    query_search_type: Literal["and", "or"] = "and",
) -> SearchRank | None:
    """
    Builds a search rank where search fields are weighted according to the configuration and
    the search query gets processed to allow searching as you type.

    Returns `None` for empty search (after removing unsafe characters and stop words).
    """
    vector = build_search_vector(search_fields, config=config)
    search = process_query(search_query, search_type=query_search_type)
    if search is None:
        return None
    query = SearchQuery(search, config=config, search_type="raw")
    return SearchRank(vector, query)

import functools
import re
from typing import Literal

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

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


def build_search_vector(search_fields: dict[str, Literal["A", "B", "C"]]) -> SearchVector:
    """
    Builds a search vector from a dict, whereby the key is the search field and the value
    is the Postgres weight e.g. `{"name": "A", "description": "C"}`.
    """
    search_vectors = [SearchVector(key, weight=value, config="simple") for key, value in search_fields.items()]
    combined_vector = functools.reduce(lambda a, b: a + b, search_vectors)
    return combined_vector


def build_rank(search_fields: dict[str, Literal["A", "B", "C"]], search_query: str) -> SearchRank | None:
    """
    Builds a "simple" search rank that converts the input to lower case and removes stop words,
    but does not do additional stemming. Search fields are weighted according to the configuration and
    the search query gets processed to allow searching as you type.

    Returns none for empty search (after removing unsafe characters and stop words).
    """
    vector = build_search_vector(search_fields)
    search = process_query(search_query)
    if search is None:
        return None
    query = SearchQuery(search, config="simple", search_type="raw")
    return SearchRank(vector, query)

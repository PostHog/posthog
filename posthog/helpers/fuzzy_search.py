"""Core fuzzy-search helpers built on rapidfuzz.

Use these for typo-tolerant, separator- and order-insensitive matching of short
strings (channel names, labels, entity names) against an in-memory candidate
list — e.g. filtering a list fetched from a third-party API where Postgres
trigram search (see ``trigram_search.py``) isn't an option. For anything already
in the database, prefer a database-side search instead.
"""

from collections.abc import Callable, Iterable
from typing import TypeVar

from rapidfuzz import fuzz, process, utils

T = TypeVar("T")

# Scores run 0-100. 70 keeps reordered, partial-token and single-typo queries while dropping unrelated strings.
DEFAULT_SCORE_CUTOFF = 70.0

# WRatio blends ratio, partial-ratio and token-set scoring, so it tolerates separators, reordering and partial tokens.
_DEFAULT_SCORER = fuzz.WRatio


def fuzzy_score(query: str, choice: str, *, scorer: Callable[..., float] = _DEFAULT_SCORER) -> float:
    """Similarity score (0-100) between ``query`` and ``choice``, case- and separator-insensitive."""
    return scorer(query, choice, processor=utils.default_process)


def fuzzy_rank(
    query: str,
    choices: Iterable[str],
    *,
    score_cutoff: float = DEFAULT_SCORE_CUTOFF,
    limit: int | None = None,
    scorer: Callable[..., float] = _DEFAULT_SCORER,
) -> list[tuple[str, float]]:
    """Rank ``choices`` by similarity to ``query``, best first, dropping anything below ``score_cutoff``."""
    matches = process.extract(
        query,
        list(choices),
        scorer=scorer,
        processor=utils.default_process,
        score_cutoff=score_cutoff,
        limit=limit,
    )
    return [(choice, score) for choice, score, _ in matches]


def fuzzy_filter(
    query: str,
    items: Iterable[T],
    key: Callable[[T], str],
    *,
    score_cutoff: float = DEFAULT_SCORE_CUTOFF,
    limit: int | None = None,
    scorer: Callable[..., float] = _DEFAULT_SCORER,
) -> list[T]:
    """Filter and rank arbitrary ``items`` by fuzzy match on ``key(item)``, best first.

    Items whose key scores below ``score_cutoff`` are dropped. Ties preserve the
    input order, so callers get a deterministic result.
    """
    items_list = list(items)
    keys = [key(item) for item in items_list]
    matches = process.extract(
        query,
        keys,
        scorer=scorer,
        processor=utils.default_process,
        score_cutoff=score_cutoff,
        limit=limit,
    )
    return [items_list[index] for _, _, index in matches]

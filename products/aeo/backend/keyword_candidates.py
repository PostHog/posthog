"""Keywords Jev picks from phrases the project already has, instead of keywords Claude writes.

The phrases come from the tracked questions, their topics, the description, the web searches the engines ran
and, when a caller has it, the site's own page text. Jev scores each phrase on whether it is worth tracking,
and the highest-scored ones become the suggestions. Nothing here writes new wording: a keyword is always a
phrase that already appeared somewhere, so it can match word for word the way the keyword report matches.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence

from posthog.dataclasses import frozen

from products.aeo.backend import decisions
from products.aeo.backend.facade.contracts import KEYWORD_MAX_LENGTH, KeywordSuggestion, KeywordSuggestionRequest
from products.aeo.backend.keywords import normalize_keyword

MAX_CANDIDATES = 96
MIN_WORD_CHARS = 3
# A phrase that one source says once is noise; one that two sources share, or one source repeats, is a term.
MIN_OCCURRENCES = 2
MIN_PHRASE_WORDS = 2
KEEP_PROBABILITY = 0.5
FEATURE = "keyword_selection"

# Words a keyword never starts or ends with, in English and Portuguese: the two languages the tracked
# questions come in today. A phrase can still carry one in the middle, as in "feature flags for mobile".
_STOP_WORDS = frozenset(
    """
a an the and or but if because as until while of at by for with about against between into through during
before after above below to from up down in out on off over under again further then once here there when
where why how all any both each few more most other some such no nor not only own same so than too very can
will just should now i me my we our you your he she it its they them their what which who whom this that
these those am is are was were be been being have has had having do does did doing would could might must
shall may also like get got use using used need needs want wants best top good better vs versus
o os as um uma uns umas e ou mas se porque como até enquanto de do da dos das em no na nos nas por para com
sobre entre durante antes depois sem sob desde ao aos à às que qual quais quem onde quando quanto este esta
estes estas esse essa esses essas aquele aquela isso isto aquilo eu tu ele ela nós vós eles elas meu minha
seu sua nosso nossa é são foi foram ser estar tem têm ter há não sim mais menos muito pouco já ainda também
melhor melhores qual
""".split()
)
_WORD = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)

_QUESTION = (
    "Is `{key}` a keyword worth tracking for the AI visibility of `site`: a product category, a feature, a use "
    "case or a problem that a buyer of what `site` sells would type into an AI assistant, where the brand should "
    "come up in the answer?"
)
_TRUE = (
    "A clear, self-contained phrase about the category, a feature, a use case or a problem the site solves, "
    "written the way a person types it."
)
_FALSE = (
    "A fragment that is not a phrase on its own, a generic word, a brand or company name, a place or a date, "
    "a phrase about something the site does not sell, or wording nobody would type."
)


@frozen
class KeywordCandidate:
    """A phrase found in the project's material, with where it came from."""

    keyword: str
    # Distinct texts the phrase appeared in, by source: prompt, topic, description, search or page.
    sources: Mapping[str, int]

    @property
    def occurrences(self) -> int:
        return sum(self.sources.values())


def _phrases(text: str, *, max_words: int) -> set[str]:
    """Every run of one to `max_words` words that neither starts nor ends with a stop word."""
    words = [match.group().lower() for match in _WORD.finditer(text)]
    found: set[str] = set()
    for start, first in enumerate(words):
        if first in _STOP_WORDS or len(first) < MIN_WORD_CHARS:
            continue
        for end in range(start + 1, min(start + max_words, len(words)) + 1):
            last = words[end - 1]
            if last in _STOP_WORDS or len(last) < MIN_WORD_CHARS:
                continue
            phrase = " ".join(words[start:end])
            if any(char.isalpha() for char in phrase) and len(phrase) <= KEYWORD_MAX_LENGTH:
                found.add(phrase)
    return found


def _names_a_term(keyword: str, terms: frozenset[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", keyword) for term in terms)


def extract_candidates(
    texts: Mapping[str, Sequence[str]],
    *,
    max_words: int,
    existing_keywords: frozenset[str],
    excluded_terms: frozenset[str],
    limit: int = MAX_CANDIDATES,
) -> list[KeywordCandidate]:
    """The phrases most worth asking about, from `texts` keyed by source. A phrase counts once per text it
    appears in. A search a person typed is a candidate on its own; anything else must appear twice and be at
    least two words. Ranked by how many sources share the phrase, then by occurrences."""
    per_source: dict[str, Counter[str]] = {}
    for source, items in texts.items():
        counts: Counter[str] = Counter()
        for item in items:
            counts.update(_phrases(item, max_words=max_words))
        per_source[source] = counts
    phrases = {phrase for counts in per_source.values() for phrase in counts}
    candidates: list[KeywordCandidate] = []
    for phrase in phrases:
        keyword = normalize_keyword(phrase)
        if keyword in existing_keywords or _names_a_term(keyword, excluded_terms):
            continue
        sources = {source: counts[phrase] for source, counts in per_source.items() if counts[phrase]}
        candidate = KeywordCandidate(keyword=keyword, sources=sources)
        # A search is a phrase a person typed, so it stands on its own. Anything else must recur, and a lone
        # word ("fees", "stays") is a fragment unless someone searched for exactly that.
        searched = "search" in sources
        if searched or (candidate.occurrences >= MIN_OCCURRENCES and len(keyword.split()) >= MIN_PHRASE_WORDS):
            candidates.append(candidate)
    # Among phrases that score alike, the longer one is the more specific, and a stable name order keeps runs comparable.
    candidates.sort(key=lambda c: (-len(c.sources), -c.occurrences, -len(c.keyword.split()), c.keyword))
    return _without_nested_duplicates(candidates)[:limit]


def _without_nested_duplicates(candidates: list[KeywordCandidate]) -> list[KeywordCandidate]:
    """Drop a phrase whose every occurrence is inside a longer kept phrase with the same counts, such as
    "replay tool" next to "session replay tool", so the model is not asked about the same term twice."""
    kept: list[KeywordCandidate] = []
    for candidate in candidates:
        if any(
            candidate.keyword in other.keyword
            and candidate.keyword != other.keyword
            and dict(candidate.sources) == dict(other.sources)
            for other in kept
        ):
            continue
        kept.append(candidate)
    return kept


def _reason(candidate: KeywordCandidate) -> str:
    parts = []
    if prompts := candidate.sources.get("prompt"):
        parts.append(f"{prompts} tracked question{'s' if prompts != 1 else ''}")
    if searches := candidate.sources.get("search"):
        parts.append(f"{searches} engine search{'es' if searches != 1 else ''}")
    if candidate.sources.get("page"):
        parts.append("the site's own pages")
    if candidate.sources.get("topic") or candidate.sources.get("description"):
        parts.append("the project's topics")
    return "Appears in " + ", ".join(parts) + "." if parts else ""


@frozen
class ScoredCandidate:
    candidate: KeywordCandidate
    probability: float


def score_candidates(
    team_id: int,
    request: KeywordSuggestionRequest,
    candidates: Sequence[KeywordCandidate],
    *,
    usage: list[decisions.DecisionUsage] | None = None,
) -> list[ScoredCandidate]:
    """Every candidate with Jev's probability that it is worth tracking, the most likely first. Raises
    `decisions.DecisionError` when the model gives no usable answer."""
    if not candidates:
        return []
    context = {
        "site": request.domain[:200],
        "brand": request.brand[:200] or "unknown",
        "description": request.description[:1000] or "unknown",
    }
    probabilities = decisions.yes_probabilities(
        team_id=team_id,
        feature=FEATURE,
        context=context,
        items=[candidate.keyword for candidate in candidates],
        item_key="phrases",
        question=_QUESTION,
        criteria_true=_TRUE,
        criteria_false=_FALSE,
        usage=usage,
    )
    scored = [ScoredCandidate(candidate=c, probability=p) for c, p in zip(candidates, probabilities)]
    return sorted(scored, key=lambda item: (-item.probability, -item.candidate.occurrences))


def select_keywords(
    team_id: int,
    request: KeywordSuggestionRequest,
    candidates: Sequence[KeywordCandidate],
    *,
    count: int,
    searches: Sequence[Sequence[str]],
    usage: list[decisions.DecisionUsage] | None = None,
) -> list[KeywordSuggestion]:
    """The `count` candidates Jev rates most worth tracking, the most likely first. Raises
    `decisions.DecisionError` when the model gives no usable answer."""
    return [
        KeywordSuggestion(
            keyword=item.candidate.keyword,
            reason=_reason(item.candidate),
            searched_checks=sum(1 for check in searches if any(item.candidate.keyword in search for search in check)),
        )
        for item in score_candidates(team_id, request, candidates, usage=usage)[:count]
        if item.probability >= KEEP_PROBABILITY
    ]

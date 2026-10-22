import re
import math
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

from django.db import connections, transaction
from django.db.models import Case, Q, QuerySet, Value, When

from rapidfuzz.distance import OSA

from posthog.dataclasses import frozen
from posthog.models.file_system.file_system import SEARCH_NAME, SEARCH_TEXT, FileSystem, split_path
from posthog.models.file_system.file_system_view_log import FileSystemViewLog

WORD_RE = re.compile(r"\w+", re.UNICODE)
CANDIDATE_LIMIT = 2000
TYPO_TOKENS_THRESHOLD = 50
MIN_WORD_SIMILARITY = 0.4
FRECENCY_HALF_LIFE_DAYS = 14
MAX_TOKENS = 8
MIN_NAME_ORDER_TOKEN_LENGTH = 3
CANDIDATE_FIELDS = ("id", "path", "type", "ref", "created_at")

EQUAL, STARTS_WITH, WORD_STARTS_WITH, CONTAINS, ACRONYM, NO_MATCH = range(6)


def words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def path_segments(path: str) -> list[str]:
    if "\\" in path:
        return split_path(path)
    return [segment for segment in path.split("/") if segment]


def basename(path: str) -> str:
    segments = path_segments(path)
    return segments[-1] if segments else ""


def singular(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def singular_text(text: str) -> str:
    return " ".join(singular(word) for word in words(text))


def allowed_typos(token: str) -> int:
    if len(token) < 5:
        return 0
    return 1 if len(token) < 9 else 2


def token_typos(token: str, word: str) -> int | None:
    if word.startswith(token) or word == singular(token):
        return 0
    budget = allowed_typos(token)
    if not budget:
        return None
    distance = min(
        OSA.distance(token, word[: len(token)]), OSA.distance(token, word), OSA.distance(token, singular(word))
    )
    return distance if distance <= budget else None


@frozen
class WordMatch:
    typos: int
    position: int


@frozen
class FileRef:
    type: str
    ref: str


def best_match(token: str, candidates: Sequence[str]) -> WordMatch | None:
    best: WordMatch | None = None
    for position, word in enumerate(candidates):
        typos = token_typos(token, word)
        if typos is not None and (best is None or typos < best.typos):
            best = WordMatch(typos=typos, position=position)
            if typos == 0:
                break
    return best


def exactness(query: str, singular_query: str, name: str, singular_name: str, name_words: Sequence[str]) -> int:
    if name == query or singular_name == singular_query:
        return EQUAL
    if name.startswith(query):
        return STARTS_WITH
    if any(word.startswith(query) for word in name_words) or re.search(r"(^|\W)" + re.escape(query), name):
        return WORD_STARTS_WITH
    if query in name:
        return CONTAINS
    if "".join(word[0] for word in name_words).startswith(query.replace(" ", "")):
        return ACRONYM
    return NO_MATCH


@frozen
class RankedEntry:
    entry: FileSystem
    rank: tuple[int, ...]
    matched_tokens: tuple[str, ...]


@frozen
class RankedSearchResult:
    entries: list[RankedEntry]
    matched_all_words: bool
    matched_with_typos: bool
    type_counts: dict[str, int]
    counts_capped: bool

    def top(self, limit: int, *, per_type: int = 0) -> list[RankedEntry]:
        kept = set(range(min(limit, len(self.entries))))
        if per_type:
            names: dict[str, set[str]] = {}
            for index, ranked in enumerate(self.entries):
                type_names = names.setdefault(ranked.entry.type, set())
                name = singular_text(basename(ranked.entry.path))
                if name not in type_names and len(type_names) < per_type:
                    type_names.add(name)
                    kept.add(index)
        return [self.entries[index] for index in sorted(kept)]


@contextmanager
def search_session(using: str) -> Iterator[None]:
    with transaction.atomic(using=using), connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT set_config('jit', 'off', true), set_config('pg_trgm.word_similarity_threshold', %s, true)",
            [str(MIN_WORD_SIMILARITY)],
        )
        yield


class FileSystemRankedSearch:
    def __init__(self, query: str, *, user_id: int, team_id: int, today: date) -> None:
        self.query = " ".join(query.lower().split())
        self.tokens = tuple(dict.fromkeys(words(self.query)))[:MAX_TOKENS]
        self.singular_query = singular_text(self.query)
        self.user_id = user_id
        self.team_id = team_id
        self.today = today
        self.last_viewed: dict[FileRef, datetime] = {}
        self.capped = False

    def word_match(self, token: str, typos: bool) -> Q:
        match = Q(search_text__contains=singular(token))
        if typos and allowed_typos(token):
            match |= Q(search_name__trigram_word_similar=token)
        return match

    @property
    def filter_tokens(self) -> tuple[str, ...]:
        return tuple(token for token in self.tokens if len(token) > 1) or self.tokens

    def every_word(self, typos: bool) -> Q:
        return Q(*(self.word_match(token, typos) for token in self.filter_tokens))

    def any_word(self, typos: bool) -> Q:
        match = Q()
        for token in self.filter_tokens:
            match |= self.word_match(token, typos)
        return match

    def fetch(self, queryset: QuerySet[FileSystem], match: Q, seen: list[FileSystem]) -> list[FileSystem]:
        ordering: list[Any] = ["-created_at"]
        name_tokens = [token for token in self.filter_tokens if len(token) >= MIN_NAME_ORDER_TOKEN_LENGTH]
        if name_tokens:
            word_starts = Q(*(Q(search_name__regex=r"\m" + re.escape(singular(token))) for token in name_tokens))
            ordering.insert(0, Case(When(word_starts, then=Value(0)), default=Value(1)))
        found = list(
            queryset.filter(match).exclude(id__in=[entry.id for entry in seen]).order_by(*ordering)[:CANDIDATE_LIMIT]
        )
        self.capped = self.capped or len(found) >= CANDIDATE_LIMIT
        return seen + found

    def search(self, queryset: QuerySet[FileSystem]) -> RankedSearchResult:
        queryset = (
            queryset.select_related(None)
            .only(*CANDIDATE_FIELDS)
            .alias(search_text=SEARCH_TEXT, search_name=SEARCH_NAME)
        )
        found = self.fetch(queryset, self.every_word(typos=False), [])
        result = self.rank(found)
        if len(result.entries) >= TYPO_TOKENS_THRESHOLD:
            return result
        if any(allowed_typos(token) for token in self.tokens):
            found = self.fetch(queryset, self.every_word(typos=True), found)
            result = self.rank(found)
        if result.matched_all_words or len(self.tokens) == 1:
            return result
        found = self.fetch(queryset, self.any_word(typos=False), found)
        result = self.rank(found)
        if not result.entries:
            found = self.fetch(queryset, self.any_word(typos=True), found)
            result = self.rank(found)
        return result

    def frecency(self, entries: Iterable[FileSystem]) -> dict[FileRef, float]:
        keys = {FileRef(type=entry.type, ref=entry.ref) for entry in entries if entry.ref}
        if not keys:
            return {}
        logs = FileSystemViewLog.objects.filter(
            team_id=self.team_id,
            user_id=self.user_id,
            type__in={key.type for key in keys},
            ref__in={key.ref for key in keys},
        ).values_list("type", "ref", "view_days", "viewed_at")
        scores: dict[FileRef, float] = {}
        for type_, ref, view_days, viewed_at in logs:
            key = FileRef(type=type_, ref=ref)
            self.last_viewed[key] = viewed_at
            days = view_days or [viewed_at.date()]
            scores[key] = sum(math.pow(0.5, max((self.today - day).days, 0) / FRECENCY_HALF_LIFE_DAYS) for day in days)
        return scores

    def rank_entry(self, entry: FileSystem, frecency: float) -> RankedEntry | None:
        segments = path_segments(entry.path)
        name = segments[-1].lower() if segments else ""
        name_words = words(name)
        singular_name = " ".join(singular(word) for word in name_words)
        other_words = words(" ".join([*segments[:-1], entry.type]))
        singular_words = {singular(word) for word in (*name_words, *other_words)}
        matched, typos, in_name, exact_words = 0, 0, 0, 0
        positions: list[int] = []
        matched_tokens: list[str] = []
        for token in self.tokens:
            name_hit = best_match(token, name_words)
            other_hit = None if name_hit and not name_hit.typos else best_match(token, other_words)
            if name_hit and (other_hit is None or name_hit.typos <= other_hit.typos):
                hit: WordMatch | None = name_hit
                in_name += 1
                positions.append(name_hit.position)
            else:
                hit = other_hit
            if hit is None:
                continue
            matched += 1
            typos += hit.typos
            matched_tokens.append(token)
            if len(self.tokens) > 1 and singular(token) in singular_words:
                exact_words += 1
        if len(self.tokens) == 1 and singular_name == self.singular_query:
            exact_words = 1
        if not matched:
            return None
        proximity = sum(max(abs(b - a) - 1, 0) + (1 if b < a else 0) for a, b in zip(positions, positions[1:]))
        attribute = 0 if in_name == len(self.tokens) else 1 if in_name else 2
        rank = (
            -matched,
            typos,
            proximity,
            attribute,
            -exact_words,
            min(positions) if positions else 99,
            exactness(self.query, self.singular_query, name, singular_name, name_words),
            -int(frecency * 1000),
            -int(entry.created_at.timestamp()),
        )
        return RankedEntry(entry=entry, rank=rank, matched_tokens=tuple(matched_tokens))

    def rank(self, candidates: list[FileSystem]) -> RankedSearchResult:
        frecency = self.frecency(candidates)
        ranked = [
            ranked_entry
            for entry in candidates
            if (
                ranked_entry := self.rank_entry(entry, frecency.get(FileRef(type=entry.type, ref=entry.ref or ""), 0.0))
            )
            is not None
        ]
        most_words = max((-r.rank[0] for r in ranked), default=0)
        matching = [r for r in ranked if -r.rank[0] == most_words]
        fewest_typos = min((r.rank[1] for r in matching), default=0)
        pool = [r for r in matching if r.rank[1] == fewest_typos]
        pool.sort(key=lambda r: r.rank)
        return RankedSearchResult(
            entries=pool,
            matched_all_words=bool(matching) and most_words == len(self.tokens),
            matched_with_typos=fewest_typos > 0,
            type_counts=dict(Counter(r.entry.type for r in pool)),
            counts_capped=self.capped,
        )

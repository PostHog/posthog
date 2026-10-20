import re
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Q, QuerySet
from django.db.models.functions import Lower

from rapidfuzz.distance import OSA

from posthog.dataclasses import frozen
from posthog.models.file_system.file_system import FileSystem, split_path
from posthog.models.file_system.file_system_view_log import FileSystemViewLog

WORD_RE = re.compile(r"\w+", re.UNICODE)
CANDIDATE_LIMIT = 2000
TYPO_CANDIDATE_LIMIT = 300
TYPO_TOKENS_THRESHOLD = 50
MIN_TRIGRAM_SIMILARITY = 0.3
FRECENCY_HALF_LIFE_DAYS = 14

EQUAL, STARTS_WITH, WORD_STARTS_WITH, CONTAINS, ACRONYM, NO_MATCH = range(6)


def words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def basename(path: str) -> str:
    segments = split_path(path)
    return segments[-1] if segments else ""


def folder(path: str) -> str:
    return " ".join(split_path(path)[:-1])


def singular(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def singular_text(text: str) -> str:
    return " ".join(singular(word) for word in words(text))


def allowed_typos(token: str) -> int:
    if len(token) < 5:
        return 0
    return 1 if len(token) < 9 else 2


def token_typos(token: str, word: str) -> int | None:
    if word.startswith(token):
        return 0
    budget = allowed_typos(token)
    if not budget:
        return None
    distance = min(OSA.distance(token, word[: len(token)]), OSA.distance(token, word))
    return distance if distance <= budget else None


def best_match(token: str, candidates: Sequence[str]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for position, word in enumerate(candidates):
        typos = token_typos(token, word)
        if typos is not None and (best is None or typos < best[0]):
            best = (typos, position)
            if typos == 0:
                break
    return best


def exactness(query: str, name: str, name_words: Sequence[str]) -> int:
    if name == query or singular_text(name) == singular_text(query):
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
    tokens: tuple[str, ...]
    matched_all_words: bool
    type_counts: dict[str, int]

    def top(self, limit: int, *, per_type: int = 0) -> list[RankedEntry]:
        kept = set(range(min(limit, len(self.entries))))
        if per_type:
            names: dict[str, set[str]] = {}
            for index, ranked in enumerate(self.entries):
                type_names = names.setdefault(ranked.entry.type, set())
                name = singular_text(basename(ranked.entry.path))
                if name in type_names:
                    kept.add(index)
                elif len(type_names) < per_type:
                    type_names.add(name)
                    kept.add(index)
        return [self.entries[index] for index in sorted(kept)]


class FileSystemRankedSearch:
    def __init__(self, query: str, *, user_id: int, team_id: int, today: date) -> None:
        self.query = " ".join(query.lower().split())
        self.tokens = tuple(words(self.query))
        self.user_id = user_id
        self.team_id = team_id
        self.today = today

    def candidates(self, queryset: QuerySet[FileSystem]) -> list[FileSystem]:
        if not self.tokens:
            return []
        all_words = Q()
        for token in self.tokens:
            all_words &= Q(path__icontains=token) | Q(type__icontains=token)
        exact = list(queryset.filter(all_words).order_by("-created_at")[:CANDIDATE_LIMIT])
        if len(self.query) < 3 or len(exact) >= TYPO_TOKENS_THRESHOLD:
            return exact
        seen = {entry.id for entry in exact}
        typos = (
            queryset.exclude(id__in=seen)
            .annotate(similarity=TrigramWordSimilarity(self.query, Lower("path")))
            .filter(similarity__gte=MIN_TRIGRAM_SIMILARITY)
            .order_by("-similarity")[:TYPO_CANDIDATE_LIMIT]
        )
        return exact + list(typos)

    def frecency(self, entries: Iterable[FileSystem]) -> dict[tuple[str, str], float]:
        keys = {(entry.type, entry.ref) for entry in entries if entry.ref}
        if not keys:
            return {}
        logs = FileSystemViewLog.objects.filter(
            team_id=self.team_id, user_id=self.user_id, type__in={k[0] for k in keys}, ref__in={k[1] for k in keys}
        ).values_list("type", "ref", "view_days", "viewed_at")
        scores: dict[tuple[str, str], float] = {}
        for type_, ref, view_days, viewed_at in logs:
            days = view_days or [viewed_at.date()]
            scores[(type_, ref)] = sum(
                math.pow(0.5, max((self.today - day).days, 0) / FRECENCY_HALF_LIFE_DAYS) for day in days
            )
        return scores

    def rank_entry(self, entry: FileSystem, frecency: float) -> RankedEntry | None:
        name = basename(entry.path).lower()
        name_words = words(name)
        other_words = words(f"{folder(entry.path)} {entry.type}")
        matched, typos, in_name, exact_words = 0, 0, 0, 0
        positions: list[int] = []
        matched_tokens: list[str] = []
        for token in self.tokens:
            hit = best_match(token, name_words)
            if hit is not None:
                in_name += 1
                positions.append(hit[1])
            else:
                hit = best_match(token, other_words)
            if hit is None:
                continue
            matched += 1
            typos += hit[0]
            matched_tokens.append(token)
            if singular(token) in {singular(word) for word in (*name_words, *other_words)}:
                exact_words += 1
        if not matched:
            return None
        proximity = sum(abs(b - a) - 1 for a, b in zip(positions, positions[1:]))
        attribute = 0 if in_name == len(self.tokens) else 1 if in_name else 2
        rank = (
            -matched,
            typos,
            proximity,
            attribute,
            -exact_words,
            min(positions) if positions else 99,
            exactness(self.query, name, name_words),
            -int(frecency * 1000),
            -int(entry.created_at.timestamp()),
        )
        return RankedEntry(entry=entry, rank=rank, matched_tokens=tuple(matched_tokens))

    def rank(self, candidates: list[FileSystem]) -> RankedSearchResult:
        frecency = self.frecency(candidates)
        ranked = [
            ranked_entry
            for entry in candidates
            if (ranked_entry := self.rank_entry(entry, frecency.get((entry.type, entry.ref or ""), 0.0))) is not None
        ]
        full = [r for r in ranked if -r.rank[0] == len(self.tokens)]
        pool = full or ranked
        pool.sort(key=lambda r: r.rank)
        return RankedSearchResult(
            entries=pool,
            tokens=self.tokens,
            matched_all_words=bool(full),
            type_counts=dict(Counter(r.entry.type for r in pool)),
        )

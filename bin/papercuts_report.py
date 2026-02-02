#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "also",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "back",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "down",
    "during",
    "each",
    "else",
    "even",
    "few",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "here",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "less",
    "like",
    "more",
    "most",
    "no",
    "not",
    "now",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "own",
    "same",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "through",
    "to",
    "too",
    "under",
    "up",
    "very",
    "via",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "will",
    "with",
    "within",
    "without",
    "you",
    "your",
    "posthog",
    "analytics",
    "platform",
    "issue",
    "issues",
    "bug",
    "bugs",
    "fix",
    "fixed",
    "fixes",
    "improve",
    "improves",
    "improved",
    "improvement",
    "feature",
    "features",
    "support",
    "request",
    "requests",
    "ticket",
    "tickets",
    "commit",
    "posthoghelp",
    "additional",
    "context",
    "steps",
    "reproduce",
    "expected",
    "actual",
    "behavior",
    "result",
    "results",
    "report",
    "reports",
    "https",
    "http",
    "www",
    "com",
}


@dataclasses.dataclass(frozen=True)
class IssueItem:
    identifier: str
    title: str
    body: str
    url: str
    repository: str
    number: int | None
    labels: tuple[str, ...]
    status: str | None
    issue_type: str | None
    user_impact: float | None
    start_date: dt.date | None
    tokens: frozenset[str]


@dataclasses.dataclass
class ScoredItem:
    item: IssueItem
    score: float
    reasons: list[str]
    keyword_hits: list[str]


@dataclasses.dataclass
class Cluster:
    tokens: frozenset[str]
    items: list[ScoredItem]


@dataclasses.dataclass(frozen=True)
class Pattern:
    name: str
    regex: re.Pattern[str]
    weight: float


PATTERNS: tuple[Pattern, ...] = (
    Pattern("rage clicks", re.compile(r"rage\\s+clicks?", re.IGNORECASE), 3.0),
    Pattern("exception", re.compile(r"exception|stack\\s*trace|traceback", re.IGNORECASE), 2.5),
    Pattern("crash", re.compile(r"crash|segfault|panic", re.IGNORECASE), 3.0),
    Pattern("timeout", re.compile(r"timeout|timed\\s+out", re.IGNORECASE), 2.0),
    Pattern("auth", re.compile(r"unauthorized|forbidden|permission\\s+denied|\\b401\\b|\\b403\\b", re.IGNORECASE), 2.0),
    Pattern("server error", re.compile(r"\\b5\\d\\d\\b", re.IGNORECASE), 2.5),
    Pattern("performance", re.compile(r"slow|latency|performance|perf", re.IGNORECASE), 1.5),
    Pattern("not working", re.compile(r"not\\s+working|broken|fails?|failure|regression", re.IGNORECASE), 2.0),
    Pattern("incorrect", re.compile(r"incorrect|wrong|misleading", re.IGNORECASE), 1.5),
    Pattern("missing data", re.compile(r"missing\\s+data|dropped|data\\s+loss", re.IGNORECASE), 2.0),
    Pattern("duplicate", re.compile(r"duplicate|duplicated", re.IGNORECASE), 1.0),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a papercuts report from GitHub project export JSON.")
    default_path = Path.home() / "gh_project_160.json"
    parser.add_argument(
        "--gh-path",
        type=Path,
        default=default_path,
        help=f"Path to gh project export JSON (default: {default_path})",
    )
    parser.add_argument("--team-label", type=str, default="team/analytics-platform", help="Team label to filter by")
    parser.add_argument("--include-unlabeled", action="store_true", help="Include items with no labels")
    parser.add_argument("--since-days", type=int, default=30, help="Time window in days")
    parser.add_argument("--ignore-date-filter", action="store_true", help="Ignore the date filter")
    parser.add_argument("--include-closed", action="store_true", help="Include items with status Done/Closed")
    parser.add_argument("--similarity-threshold", type=float, default=0.35, help="Jaccard similarity threshold")
    parser.add_argument("--max-clusters", type=int, default=15, help="Max clusters to show")
    parser.add_argument("--max-items", type=int, default=5, help="Max items per cluster to show")
    return parser.parse_args()


def coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def coerce_list_str(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items: list[str] = []
    for item in value:
        if item is None:
            continue
        items.append(str(item))
    return tuple(items)


def coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not math.isnan(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def parse_date(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        pass
    try:
        return dt.datetime.fromisoformat(value).date()
    except ValueError:
        return None


def tokenize(text: str) -> frozenset[str]:
    without_urls = re.sub(r"https?://\\S+", " ", text)
    cleaned = re.sub(r"[^a-z0-9]+", " ", without_urls.lower())
    tokens: list[str] = []
    for token in cleaned.split():
        if len(token) <= 2 or token in STOPWORDS:
            continue
        if len(token) > 24:
            continue
        if any(char.isdigit() for char in token) and not token.isdigit() and len(token) > 4:
            continue
        if re.fullmatch(r"[a-f0-9]{10,}", token):
            continue
        tokens.append(token)
    return frozenset(tokens)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 0.0
    intersection = left.intersection(right)
    union = left.union(right)
    if not union:
        return 0.0
    return len(intersection) / len(union)


def issue_identifier(repository: str, number: int | None, fallback: str) -> str:
    if repository and number is not None:
        return f"{repository}#{number}"
    if repository:
        return repository
    return fallback


def load_items(path: Path) -> list[IssueItem]:
    with path.open() as handle:
        raw = json.load(handle)
    items_raw = raw.get("items")
    if not isinstance(items_raw, list):
        raise ValueError("Expected top-level 'items' list in gh export JSON")

    items: list[IssueItem] = []
    for entry in items_raw:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        content_dict = content if isinstance(content, dict) else {}
        content_type = coerce_str(content_dict.get("type"))
        if content_type and content_type.lower() != "issue":
            continue

        title = coerce_str(content_dict.get("title") or entry.get("title"))
        body = coerce_str(content_dict.get("body"))
        url = coerce_str(content_dict.get("url"))
        repository = coerce_str(content_dict.get("repository") or entry.get("repository"))
        number = coerce_int(content_dict.get("number"))
        labels = coerce_list_str(entry.get("labels"))
        status = coerce_str(entry.get("status")) or None
        issue_type = coerce_str(entry.get("issue Type")) or None
        user_impact = coerce_float(entry.get("user Impact"))
        start_date = parse_date(entry.get("start date"))

        identifier = issue_identifier(repository, number, coerce_str(entry.get("id")))
        tokens = tokenize(title)

        items.append(
            IssueItem(
                identifier=identifier,
                title=title,
                body=body,
                url=url,
                repository=repository,
                number=number,
                labels=labels,
                status=status,
                issue_type=issue_type,
                user_impact=user_impact,
                start_date=start_date,
                tokens=tokens,
            )
        )
    return items


def score_item(item: IssueItem) -> ScoredItem:
    score = 1.0
    reasons: list[str] = []
    keyword_hits: list[str] = []
    if item.issue_type and item.issue_type.lower() == "bug":
        score += 2.0
        reasons.append("issue type: bug")
    if item.user_impact is not None and item.user_impact > 0:
        score += min(item.user_impact, 10.0) / 2.0
        reasons.append(f"user impact: {item.user_impact:g}")
    if item.status and item.status.lower() in {"to triage", "backlog"}:
        score += 0.5
        reasons.append(f"status: {item.status}")
    if "bug" in (label.lower() for label in item.labels):
        score += 1.0
        reasons.append("label: bug")

    text = f"{item.title}\n{item.body}"
    for pattern in PATTERNS:
        if pattern.regex.search(text):
            score += pattern.weight
            keyword_hits.append(pattern.name)
            reasons.append(f"signal: {pattern.name}")
    return ScoredItem(item=item, score=score, reasons=reasons, keyword_hits=keyword_hits)


def cluster_items(items: Sequence[ScoredItem], threshold: float) -> list[Cluster]:
    clusters: list[Cluster] = []
    for scored in items:
        placed = False
        for cluster in clusters:
            if jaccard(scored.item.tokens, cluster.tokens) >= threshold:
                cluster.items.append(scored)
                cluster.tokens = frozenset(set(cluster.tokens).union(scored.item.tokens))
                placed = True
                break
        if not placed:
            clusters.append(Cluster(tokens=scored.item.tokens, items=[scored]))
    return clusters


def summarize_cluster(cluster: Cluster) -> str:
    token_counts: Counter[str] = Counter()
    for scored in cluster.items:
        token_counts.update(tokenize(scored.item.title))
    common = [token for token, _ in token_counts.most_common(5)]
    return " ".join(common) if common else "misc"


def format_status_counts(items: Sequence[ScoredItem]) -> str:
    counts: Counter[str] = Counter()
    for scored in items:
        status = scored.item.status or "Unknown"
        counts[status] += 1
    return ", ".join(f"{status}={count}" for status, count in counts.most_common())


def format_item(scored: ScoredItem) -> str:
    item = scored.item
    parts = [item.identifier, item.title]
    status = item.status or "Unknown"
    impact = f"{item.user_impact:g}" if item.user_impact is not None else "n/a"
    parts.append(f"[score {scored.score:.1f}; status {status}; impact {impact}]")
    if item.url:
        parts.append(item.url)
    return " ".join(parts)


def filter_items(
    items: Sequence[IssueItem],
    team_label: str,
    include_unlabeled: bool,
    since_date: dt.date,
    include_closed: bool,
    apply_date_filter: bool,
) -> tuple[list[IssueItem], dict[str, int]]:
    stats: dict[str, int] = {
        "excluded_team_label": 0,
        "excluded_status": 0,
        "excluded_date": 0,
        "missing_date": 0,
    }
    filtered: list[IssueItem] = []
    for item in items:
        labels_lower = {label.lower() for label in item.labels}
        if team_label and team_label.lower() not in labels_lower:
            if not (include_unlabeled and not labels_lower):
                stats["excluded_team_label"] += 1
                continue
        if not include_closed and item.status and item.status.lower() in {"done", "closed"}:
            stats["excluded_status"] += 1
            continue
        if apply_date_filter:
            if item.start_date is None:
                stats["missing_date"] += 1
                filtered.append(item)
                continue
            if item.start_date < since_date:
                stats["excluded_date"] += 1
                continue
        filtered.append(item)
    return filtered, stats


def main() -> int:
    args = parse_args()
    path = args.gh_path.expanduser()
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    items = load_items(path)
    since_date = dt.date.today() - dt.timedelta(days=args.since_days)
    filtered, stats = filter_items(
        items=items,
        team_label=args.team_label,
        include_unlabeled=args.include_unlabeled,
        since_date=since_date,
        include_closed=args.include_closed,
        apply_date_filter=not args.ignore_date_filter,
    )

    scored = [score_item(item) for item in filtered]
    scored.sort(key=lambda entry: entry.score, reverse=True)
    clusters = cluster_items(scored, args.similarity_threshold)
    clusters.sort(key=lambda cluster: sum(item.score for item in cluster.items), reverse=True)

    print("Papercuts report (GitHub project export)")
    print(f"Generated: {dt.date.today().isoformat()}")
    print(f"Source: {path}")
    print("")
    print("Summary")
    print(f"- Items loaded: {len(items)}")
    print(f"- Items included: {len(filtered)}")
    if args.team_label:
        print(f"- Team label filter: {args.team_label} (excluded {stats['excluded_team_label']})")
    if not args.include_closed:
        print(f"- Status excluded: Done/Closed (excluded {stats['excluded_status']})")
    if args.ignore_date_filter:
        print("- Date window: ignored")
    else:
        print(f"- Date window: last {args.since_days} days since {since_date.isoformat()}")
        print(f"- Missing start date: {stats['missing_date']} (included by default)")
        if stats["excluded_date"] > 0:
            print(f"- Excluded by start date: {stats['excluded_date']}")
    print("")
    if stats["missing_date"] > 0 and not args.ignore_date_filter:
        print("Note: GitHub project export does not include created/updated timestamps.")
        print("      This report uses the 'start date' field when present.")
        print("      Items missing a start date are included by default.")
        print("")

    print(f"Top clusters (showing {min(args.max_clusters, len(clusters))} of {len(clusters)})")
    for index, cluster in enumerate(clusters[: args.max_clusters], start=1):
        label = summarize_cluster(cluster)
        total_score = sum(item.score for item in cluster.items)
        print(
            f"{index}. {label} (items {len(cluster.items)}, score {total_score:.1f}, "
            f"statuses: {format_status_counts(cluster.items)})"
        )
        for item in cluster.items[: args.max_items]:
            print(f"   - {format_item(item)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

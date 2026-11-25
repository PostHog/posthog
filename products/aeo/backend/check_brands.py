"""Which catalog brands each answer names, cites or retrieved, resolved when the answer is stored.

Every brand is known by the same identifiers, whatever its kind: its name, its aliases, the label of its
domain (`example` for `example.co.uk`), and the domain itself. The parser finds them in the answer text,
in the URLs the answer cites and in the URLs the engine retrieved, and writes one row per check and brand
to `posthog_aeo_check_brand`. Reads count those rows and never match names against answer text.

A name matches as a whole phrase, case ignored: the characters on either side are not word characters,
or the text ends there. So `Yahoo!` matches in "Yahoo! Mail" and `posthog` matches in "PostHog's".
"""

from __future__ import annotations

import re
import json
import uuid
import hashlib
import datetime as dt
import operator
from collections.abc import Iterable, Sequence
from functools import reduce
from urllib.parse import urlparse

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import tldextract
from redis.lock import Lock

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.redis import get_client

from products.aeo.backend.catalog import sync_brands_from_citations
from products.aeo.backend.facade.contracts import BRAND_DOMAIN_MAX_LENGTH, MentionKind
from products.aeo.backend.facts import backfill_facts, citation_rows, has_checks_without_facts
from products.aeo.backend.models import AEOBrand, AEOCheckBrand, AEOCitationCheck
from products.aeo.backend.stored_results import bump_data_version_on_commit

# How many text mentions a row keeps. The first one decides the position; the rest show how the answer
# named the brand.
MAX_STORED_MENTIONS = 10
RESOLVE_BATCH_SIZE = 500

_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=())
_WORD = re.compile(r"\w+")
_URL = re.compile(r"https?://[^\s<>()\[\]{}\"'`]+", re.IGNORECASE)
# A bare domain such as example.com or docs.example.co.uk, not inside an email address or a longer word.
_BARE_DOMAIN = re.compile(r"(?<![\w.@-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?![\w-])")
# Which kind wins when two mentions of a brand start at the same place: "example.com" is a domain
# mention, not a mention of the label "example" inside it.
_KIND_PRIORITY = {
    MentionKind.URL: 0,
    MentionKind.DOMAIN: 1,
    MentionKind.NAME: 2,
    MentionKind.ALIAS: 3,
    MentionKind.DOMAIN_LABEL: 4,
}


def domain_label(domain: str) -> str | None:
    """The label a brand is called by, `acme` for acme.co.uk. A site on a subdomain such as
    news.ycombinator.com has none: its parent's label names a different brand."""
    domain = domain.lower().removeprefix("www.")
    parts = _DOMAIN_PARTS(domain)
    return parts.domain if parts.domain and parts.top_domain_under_public_suffix == domain else None


def normalize_name(name: str) -> str:
    return name.strip().lower()


@frozen
class BrandIdentity:
    """The identifiers one brand is found by. `terms` holds each lowercased name with the kind it came
    from; a name that is also the domain label counts as the name."""

    brand_id: uuid.UUID
    domain: str
    terms: tuple[tuple[str, MentionKind], ...]
    key: str


def brand_identity(brand_id: uuid.UUID, *, name: str, aliases: object, domain: str) -> BrandIdentity:
    named = [(normalize_name(name), MentionKind.NAME)]
    if isinstance(aliases, list):
        named += [(normalize_name(alias), MentionKind.ALIAS) for alias in aliases if isinstance(alias, str)]
    if label := domain_label(domain):
        named.append((label, MentionKind.DOMAIN_LABEL))
    terms: dict[str, MentionKind] = {}
    for term, kind in named:
        if term:
            terms.setdefault(term, kind)
    return BrandIdentity(
        brand_id=brand_id,
        domain=domain.lower(),
        terms=tuple(terms.items()),
        key=identity_key(name=name, aliases=aliases, domain=domain),
    )


def identity_key(*, name: str, aliases: object, domain: str) -> str:
    """A short fingerprint of what a brand is found by. A rename, a new alias or another domain changes it."""
    alias_terms = sorted(
        {normalize_name(a) for a in aliases if isinstance(a, str)} if isinstance(aliases, list) else []
    )
    payload = json.dumps([normalize_name(name), alias_terms, domain.lower()])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def identity_of(brand: AEOBrand) -> BrandIdentity:
    return brand_identity(brand.id, name=brand.name, aliases=brand.aliases, domain=brand.domain)


def catalog_identities(team_id: int) -> list[BrandIdentity]:
    """Every brand of the team's catalog, ignored ones included: whether a brand counts is a read's choice."""
    rows = AEOBrand.objects.for_team(team_id, canonical=True).only("id", "name", "aliases", "domain")
    return [identity_of(brand) for brand in rows]


@frozen
class Mention:
    """One place where an answer's text names a brand."""

    surface: str
    kind: MentionKind
    start: int


@frozen
class BrandMatch:
    """What one answer says about one brand."""

    brand_id: uuid.UUID
    mentions: tuple[Mention, ...]
    cited: bool
    retrieved: bool
    citation_position: int | None

    @property
    def mentioned(self) -> bool:
        return bool(self.mentions)

    @property
    def first_position(self) -> int | None:
        return self.mentions[0].start if self.mentions else None

    @property
    def matched_by(self) -> MentionKind:
        if self.mentions:
            return self.mentions[0].kind
        return MentionKind.CITATION if self.cited else MentionKind.RETRIEVAL


@frozen
class _Term:
    text: str
    # Non-word characters before the term's first word, as in ".net".
    lead: int
    brand_id: uuid.UUID
    kind: MentionKind


def _is_word(char: str) -> bool:
    return char.isalnum() or char == "_"


def fold(text: str) -> str:
    """The text lowercased, one character for one, so offsets into it are offsets into the text."""
    lowered = text.lower()
    if len(lowered) == len(text):
        return lowered
    return "".join(low if len(low := char.lower()) == 1 else char for char in text)


class BrandMatcher:
    """Finds the brands of a catalog in answers. Each name is looked up by its first word, so an answer
    costs one pass over its words whatever the size of the catalog."""

    def __init__(self, identities: Iterable[BrandIdentity]) -> None:
        self._by_word: dict[str, list[_Term]] = {}
        self._wordless: list[_Term] = []
        self._by_domain: dict[str, uuid.UUID] = {}
        for identity in identities:
            self._by_domain.setdefault(identity.domain, identity.brand_id)
            for text, kind in identity.terms:
                first = _WORD.search(text)
                if first is None:
                    self._wordless.append(_Term(text=text, lead=0, brand_id=identity.brand_id, kind=kind))
                    continue
                term = _Term(text=text, lead=first.start(), brand_id=identity.brand_id, kind=kind)
                self._by_word.setdefault(first.group(), []).append(term)

    @property
    def brand_ids(self) -> set[uuid.UUID]:
        return set(self._by_domain.values())

    def brand_for_host(self, host: str) -> uuid.UUID | None:
        """The brand whose domain is the host or one it sits under, the most specific first."""
        labels = host.lower().rstrip(".").split(".")
        for index in range(len(labels)):
            if brand_id := self._by_domain.get(".".join(labels[index:])):
                return brand_id
        return None

    def text_mentions(self, text: str) -> dict[uuid.UUID, list[Mention]]:
        folded = fold(text)
        found: dict[uuid.UUID, dict[int, Mention]] = {}

        def add(brand_id: uuid.UUID, mention: Mention) -> None:
            at = found.setdefault(brand_id, {})
            current = at.get(mention.start)
            if current is None or _KIND_PRIORITY[mention.kind] < _KIND_PRIORITY[current.kind]:
                at[mention.start] = mention

        for word in _WORD.finditer(folded):
            for term in self._by_word.get(word.group(), ()):
                start = word.start() - term.lead
                if start >= 0 and _whole(folded, term.text, start):
                    add(
                        term.brand_id,
                        Mention(surface=text[start : start + len(term.text)], kind=term.kind, start=start),
                    )
        for term in self._wordless:
            start = folded.find(term.text)
            while start >= 0:
                if _whole(folded, term.text, start):
                    add(
                        term.brand_id,
                        Mention(surface=text[start : start + len(term.text)], kind=term.kind, start=start),
                    )
                start = folded.find(term.text, start + 1)
        urls = _urls(folded)
        # A name inside a link or a domain of the same brand ("acme" in acme.com) is part of that mention.
        inside: dict[uuid.UUID, list[tuple[int, int]]] = {}
        for kind, spans in ((MentionKind.URL, urls), (MentionKind.DOMAIN, _bare_domains(folded, urls))):
            for span in spans:
                if brand_id := self.brand_for_host(span.host):
                    add(brand_id, Mention(surface=text[span.start : span.end], kind=kind, start=span.start))
                    inside.setdefault(brand_id, []).append((span.start, span.end))
        return {
            brand_id: [
                at[start]
                for start in sorted(at)
                if not any(span_start < start < span_end for span_start, span_end in inside.get(brand_id, ()))
            ]
            for brand_id, at in found.items()
        }

    def match(self, check: AEOCitationCheck) -> list[BrandMatch]:
        """The brands one check names, cites or retrieved. A failed check has none."""
        if check.check_failed:
            return []
        mentions = self.text_mentions(check.answer_text or "")
        cited: dict[uuid.UUID, int] = {}
        for row in citation_rows(check):
            if row.host and (brand_id := self.brand_for_host(row.host)):
                cited[brand_id] = min(cited.get(brand_id, row.position), row.position)
        retrieved = {
            brand_id
            for url in check.retrieved_urls or []
            if isinstance(url, str) and (brand_id := self.brand_for_host(_host(url)))
        }
        return [
            BrandMatch(
                brand_id=brand_id,
                mentions=tuple(mentions.get(brand_id, ())),
                cited=brand_id in cited,
                retrieved=brand_id in retrieved,
                citation_position=cited.get(brand_id),
            )
            for brand_id in sorted({*mentions, *cited, *retrieved}, key=str)
        ]


def _whole(folded: str, term: str, start: int) -> bool:
    end = start + len(term)
    return (
        folded.startswith(term, start)
        and (start == 0 or not _is_word(folded[start - 1]))
        and (end == len(folded) or not _is_word(folded[end]))
    )


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


@frozen
class _HostSpan:
    """Where a link or a bare domain sits in the text, and the host it names."""

    start: int
    end: int
    host: str


def _urls(folded: str) -> list[_HostSpan]:
    spans = []
    for match in _URL.finditer(folded):
        # Sentence punctuation after a link is not part of it.
        end = match.end()
        while end > match.start() and folded[end - 1] in ".,;:!?":
            end -= 1
        if (host := _host(folded[match.start() : end])) and len(host) <= BRAND_DOMAIN_MAX_LENGTH:
            spans.append(_HostSpan(start=match.start(), end=end, host=host))
    return spans


def _bare_domains(folded: str, urls: list[_HostSpan]) -> list[_HostSpan]:
    return [
        _HostSpan(start=match.start(), end=match.end(), host=match.group())
        for match in _BARE_DOMAIN.finditer(folded)
        if not any(url.start <= match.start() < url.end for url in urls) and _DOMAIN_PARTS(match.group()).suffix
    ]


def check_brand_rows(check: AEOCitationCheck, matcher: BrandMatcher) -> list[AEOCheckBrand]:
    answer_length = len(check.answer_text or "")
    return [
        AEOCheckBrand(
            team_id=check.team_id,
            citation_check_id=check.id,
            brand_id=match.brand_id,
            created_at=check.created_at,
            mentioned=match.mentioned,
            cited=match.cited,
            retrieved=match.retrieved,
            first_position=match.first_position,
            answer_length=answer_length,
            citation_position=match.citation_position,
            matched_by=match.matched_by,
            mentions=[
                {"surface": mention.surface, "kind": mention.kind.value, "start": mention.start}
                for mention in match.mentions[:MAX_STORED_MENTIONS]
            ],
        )
        for match in matcher.match(check)
    ]


def write_check_brands(
    checks: Sequence[AEOCitationCheck], matcher: BrandMatcher, *, brand_ids: set[uuid.UUID] | None = None
) -> int:
    """Write the brand rows of checks that are already saved, and return how many rows it wrote.

    The rows of these checks are replaced, so a repeated call writes the same rows. With `brand_ids`, only
    those brands' rows are replaced and the checks keep their other rows; without, every row is replaced
    and the checks are marked resolved."""
    if not checks:
        return 0
    # Every check of one call belongs to one team: a run and a backfill page are both per team.
    team_id = checks[0].team_id
    ids = [check.id for check in checks]
    rows = [row for check in checks for row in check_brand_rows(check, matcher)]
    existing = AEOCheckBrand.objects.for_team(team_id, canonical=True).filter(citation_check_id__in=ids)
    if brand_ids is not None:
        existing = existing.filter(brand_id__in=brand_ids)
        rows = [row for row in rows if row.brand_id in brand_ids]
    # One transaction, so a read never sees a check between losing its old rows and getting the new ones.
    with transaction.atomic():
        existing.delete()
        AEOCheckBrand.objects.for_team(team_id, canonical=True).bulk_create(rows, ignore_conflicts=True)
        if brand_ids is None:
            AEOCitationCheck.objects.for_team(team_id, canonical=True).filter(id__in=ids).update(
                brands_resolved_at=timezone.now()
            )
    return len(rows)


_RESOLVE_FIELDS = (
    "id",
    "team_id",
    "created_at",
    "check_failed",
    "answer_text",
    "cited_urls",
    "top_cited_domains",
    "retrieved_urls",
)


@frozen
class _ResumePoint:
    """The last check a pass resolved. Pages run from the newest check down, so the pass resumes below it."""

    created_at: dt.datetime
    id: uuid.UUID


def _pages(
    checks: QuerySet[AEOCitationCheck], *, after: _ResumePoint | None = None
) -> Iterable[list[AEOCitationCheck]]:
    # Keyset pages with a database limit: behind PgBouncer, iterator() would buffer the whole result.
    # They follow (created_at, id) from the newest check down, which the team's window index serves. The
    # oldest check comes last, so `has_unresolved_brands` stays true after a backfill that stopped early.
    query = checks.only(*_RESOLVE_FIELDS).order_by("-created_at", "-id")
    last = after
    while page := list(
        (
            query.filter(Q(created_at__lt=last.created_at) | Q(created_at=last.created_at, id__lt=last.id))
            if last
            else query
        )[:RESOLVE_BATCH_SIZE]
    ):
        last = _ResumePoint(created_at=page[-1].created_at, id=page[-1].id)
        yield page


@frozen
class ResolveResult:
    checks: int
    brands: int
    rows: int


def resolve_unresolved_checks(team_id: int) -> ResolveResult:
    """Write every brand row of the checks that have none yet: the backfill of checks recorded before
    the rows existed, and of any write that failed after its check."""
    team_id = resolve_effective_team_id(team_id)
    matcher = BrandMatcher(catalog_identities(team_id))
    checks = AEOCitationCheck.objects.for_team(team_id, canonical=True).filter(brands_resolved_at__isnull=True)
    return _resolve(checks, matcher, brand_ids=None)


def resolve_run(team_id: int, run_id: str) -> ResolveResult:
    """Write every brand row of one run's checks again against the catalog of now. The runner wrote them
    against the catalog of the moment, which a brand edit or the brand sync may have changed since."""
    team_id = resolve_effective_team_id(team_id)
    matcher = BrandMatcher(catalog_identities(team_id))
    checks = AEOCitationCheck.objects.for_team(team_id, canonical=True).filter(run_id=run_id)
    return _resolve(checks, matcher, brand_ids=None)


def resolve_stale_brands(team_id: int) -> ResolveResult:
    """Resolve again, over the team's whole history, the brands whose name, aliases or domain changed
    since their rows were written, and the brands that never had any. Only those brands' rows are
    rewritten, so an edit to one brand never rewrites the rows of the others.

    The pass saves its place after every page, so one that its task's time limit stops resumes there.
    A brand gets its new key only when its identity is still the one the pass matched, so an edit
    that lands during the pass leaves the brand stale, and the next pass starts it over."""
    team_id = resolve_effective_team_id(team_id)
    brands = AEOBrand.objects.for_team(team_id, canonical=True)
    stale = [
        (brand, identity)
        for brand in brands.only(
            "id",
            "name",
            "aliases",
            "domain",
            "mentions_key",
            "mentions_resolving_key",
            "mentions_resolved_before",
            "mentions_resolved_before_id",
        )
        if (identity := identity_of(brand)).key != brand.mentions_key
    ]
    if not stale:
        return ResolveResult(checks=0, brands=0, rows=0)
    groups: dict[_ResumePoint | None, list[BrandIdentity]] = {}
    for brand, identity in stale:
        resume = None
        if brand.mentions_resolving_key != identity.key:
            # The brand counts as stale until a pass finishes: an edit back to the identity its rows had
            # before still finds them partly rewritten for the one this pass resolves.
            brands.filter(id=brand.id).update(
                mentions_key=None,
                mentions_resolving_key=identity.key,
                mentions_resolved_before=None,
                mentions_resolved_before_id=None,
            )
        elif brand.mentions_resolved_before and brand.mentions_resolved_before_id:
            resume = _ResumePoint(created_at=brand.mentions_resolved_before, id=brand.mentions_resolved_before_id)
        groups.setdefault(resume, []).append(identity)
    # Checks that were never resolved get every brand from `resolve_unresolved_checks`.
    resolved = AEOCitationCheck.objects.for_team(team_id, canonical=True).filter(brands_resolved_at__isnull=False)
    read = 0
    written = 0
    # The whole catalog matches, so a host goes to the brand on its most specific domain, as in a full pass:
    # news.ycombinator.com stays with its own brand when only ycombinator.com changed. Only the stale
    # brands' rows are written.
    matcher = BrandMatcher(catalog_identities(team_id))
    for resume, identities in groups.items():
        # A brand that a newer pass took over or finished no longer resolves this pass's identity.
        resolving = reduce(
            operator.or_, (Q(id=identity.brand_id, mentions_resolving_key=identity.key) for identity in identities)
        )
        for page in _pages(resolved, after=resume):
            # A pass that outlived its lock may run beside a newer one. Each page writes only the brands
            # still resolving this pass's identity, and locks them until it commits, so a newer pass takes
            # a brand over only between pages and its own writes land after this one's.
            with transaction.atomic():
                brand_ids = set(brands.filter(resolving).select_for_update().values_list("id", flat=True))
                if not brand_ids:
                    break
                written += write_check_brands(page, matcher, brand_ids=brand_ids)
                brands.filter(resolving).update(
                    mentions_resolved_before=page[-1].created_at, mentions_resolved_before_id=page[-1].id
                )
            read += len(page)
        current = {
            brand.id: identity_of(brand).key
            for brand in brands.filter(resolving).only("id", "name", "aliases", "domain")
        }
        for identity in identities:
            if current.get(identity.brand_id) == identity.key:
                brands.filter(id=identity.brand_id, mentions_resolving_key=identity.key).update(
                    mentions_key=identity.key,
                    mentions_resolving_key=None,
                    mentions_resolved_before=None,
                    mentions_resolved_before_id=None,
                )
    if read:
        bump_data_version_on_commit(team_id)
    return ResolveResult(checks=read, brands=len(stale), rows=written)


def _resolve(
    checks: QuerySet[AEOCitationCheck], matcher: BrandMatcher, *, brand_ids: set[uuid.UUID] | None
) -> ResolveResult:
    read = 0
    written = 0
    team_id = None
    for page in _pages(checks):
        team_id = page[0].team_id
        written += write_check_brands(page, matcher, brand_ids=brand_ids)
        read += len(page)
    if team_id is not None:
        bump_data_version_on_commit(team_id)
    return ResolveResult(checks=read, brands=len(matcher.brand_ids), rows=written)


def teams_with_checks() -> list[int]:
    return list(AEOCitationCheck.objects.unscoped().values_list("team_id", flat=True).distinct())


def has_unresolved_checks(team_id: int) -> bool:
    """Whether any check waits for its brand rows: one recorded before the rows existed, or one whose
    rows the runner failed to write. `aeo_check_unresolved_idx` holds only those checks."""
    return (
        AEOCitationCheck.objects.for_team(resolve_effective_team_id(team_id), canonical=True)
        .filter(brands_resolved_at__isnull=True)
        .exists()
    )


def enrich_lock(team_id: int, *, timeout: int) -> Lock:
    """The team's lock for bringing brand rows up to date. The task and the backfill command both take it,
    so two passes never interleave their writes and leave a brand marked current over older rows."""
    return get_client().lock(f"aeo_check_brands_enrich:{team_id}", timeout=timeout)


def has_stale_brands(team_id: int) -> bool:
    """Whether a brand waits for the pass over its history."""
    brands = AEOBrand.objects.for_team(resolve_effective_team_id(team_id), canonical=True).only(
        "id", "name", "aliases", "domain", "mentions_key"
    )
    return any(identity_of(brand).key != brand.mentions_key for brand in brands)


@frozen
class EnrichResult:
    brands_added: int
    stale: ResolveResult
    unresolved: ResolveResult
    run: ResolveResult | None


def enrich_check_brands(team_id: int, *, run_id: str | None = None) -> EnrichResult:
    """Bring the team's brand rows up to date: resolve the brands that changed over the history, then the
    checks that have no rows, then the given run's checks again.

    Before a backfill, every domain a stored answer cited gets a catalog row, so each cited brand has an
    entity to resolve to. The rows are replaced, never added to, so a repeated call writes the same rows."""
    team_id = resolve_effective_team_id(team_id)
    added = 0
    if has_unresolved_checks(team_id):
        # The catalog sync reads the citation rows, so checks recorded before those existed get them first.
        if has_checks_without_facts(team_id):
            backfill_facts(team_id)
        added = sync_brands_from_citations(team_id).created
    stale = resolve_stale_brands(team_id)
    unresolved = resolve_unresolved_checks(team_id)
    run = resolve_run(team_id, run_id) if run_id else None
    return EnrichResult(brands_added=added, stale=stale, unresolved=unresolved, run=run)

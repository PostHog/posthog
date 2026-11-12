"""How an answer is judged to name the brand.

The brand names are the registrable names of the target domains (`example` for
`docs.example.co.uk`), so the same list drives the SQL mention filter, the brand
regex the sentiment scorer uses, the names the frontend builds its HogQL
mention filter from, and the split between branded and non-branded prompts.
"""

from __future__ import annotations

import re
from typing import Literal

from django.db.models import Q

import tldextract

from products.aeo.backend.facade.contracts import BrandedSegment

_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=())

PromptField = Literal["prompt_text", "prompt"]

# `AEOCitationCheck` stores the prompt as `prompt_text`, `AEOPrompt` as `prompt`.
_BRANDED_LOOKUPS: dict[PromptField, str] = {"prompt_text": "prompt_text__iregex", "prompt": "prompt__iregex"}


def brand_names(target_domains: list[str]) -> tuple[str, ...]:
    """Lower-cased registrable names of the target domains, sorted, without duplicates."""
    return tuple(sorted({(_DOMAIN_PARTS(domain).domain or domain).lower() for domain in target_domains if domain}))


def brand_regex(target_domains: list[str]) -> str | None:
    """Postgres regex (word-bounded, for `iregex`) that matches any brand name. None without a brand."""
    names = brand_names(target_domains)
    if not names:
        return None
    return r"\m(" + "|".join(re.escape(name) for name in names) + r")\M"


def brand_pattern(target_domains: list[str]) -> re.Pattern[str] | None:
    """Python equivalent of `brand_regex`, for text already loaded from the database."""
    names = brand_names(target_domains)
    if not names:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(name) for name in names) + r")\b", re.IGNORECASE)


def mention_filter(target_domains: list[str]) -> Q:
    """Checks whose answer names the brand. A cited answer counts as a mention even when the
    text only carries the URL, so the mention rate is never below the citation rate."""
    mention = Q(cited=True)
    if regex := brand_regex(target_domains):
        mention |= Q(answer_text__iregex=regex)
    return mention


def branded_filter(target_domains: list[str], *, field: PromptField = "prompt_text") -> Q:
    """Rows whose prompt names the brand. Matches nothing without a brand, so every prompt reads as non-branded."""
    if regex := brand_regex(target_domains):
        return Q(**{_BRANDED_LOOKUPS[field]: regex})
    return Q(pk__in=[])


def segment_filter(segment: BrandedSegment, target_domains: list[str], *, field: PromptField = "prompt_text") -> Q:
    if segment == BrandedSegment.ALL:
        return Q()
    branded = branded_filter(target_domains, field=field)
    return branded if segment == BrandedSegment.BRANDED else ~branded


# `segment_filter` for raw SQL over `posthog_aeo_citation_check AS check_row`, with the parameters
# from `segment_sql_params`. A null regex (no brand) never matches, so no check reads as branded.
SEGMENT_SQL = "(%s = 'all' OR coalesce(check_row.prompt_text ~* %s, false) = (%s = 'branded'))"


def segment_sql_params(segment: BrandedSegment, target_domains: list[str]) -> list[str | None]:
    return [segment.value, brand_regex(target_domains), segment.value]

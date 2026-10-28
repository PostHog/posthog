"""How an answer is judged to name the brand.

The brand names are the registrable names of the target domains (`example` for
`docs.example.co.uk`), so the same list drives the SQL mention filter, the brand
regex the sentiment scorer uses, and the names the frontend builds its HogQL
mention filter from.
"""

from __future__ import annotations

import re

from django.db.models import Q

import tldextract

_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=())


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

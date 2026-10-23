"""Per-team AEO config: what counts as the team's own domain, its brand, and its
competitors when a check reads an engine's answer.

A team without a `TeamAEOConfig` row falls back to the instance-wide
`AEO_TARGET_DOMAINS` setting, with the registrable name of each domain as the
brand, so an unconfigured team keeps the behavior the POC shipped with.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from django.conf import settings

import structlog
import tldextract

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.security.llm_prompt_sanitization import GENERIC_VALUE_MAX_LEN, sanitize_user_text

from products.aeo.backend.facade.contracts import AEOConfig, AEOConfigError, Competitor
from products.aeo.backend.models import TeamAEOConfig

logger = structlog.get_logger(__name__)

MAX_TARGET_DOMAINS = 20
MAX_BRAND_NAMES = 50
MAX_COMPETITORS = 100
MAX_DOMAINS_PER_COMPETITOR = 20
# A one-character name matches somewhere in nearly every answer.
MIN_NAME_LENGTH = 2

# No suffix-list fetch: the bundled snapshot is enough to split a registrable name off a domain.
_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=())
_HOSTNAME_RE = re.compile(r"^[a-z0-9.-]+$")


def default_config() -> AEOConfig:
    target_domains = [domain for domain in settings.AEO_TARGET_DOMAINS if domain]
    return AEOConfig(
        target_domains=tuple(target_domains), brand_names=_brand_names_from(target_domains), competitors=()
    )


def resolve_config(team_id: int, *, canonical_team_id: int | None = None) -> AEOConfig:
    """The team's stored config, or the instance defaults when it has no row.

    Keyed on the canonical team so a child environment reads the same config its
    citation checks are written under. Callers that already resolved the
    canonical id pass it to skip the lookup.
    """
    if canonical_team_id is None:
        canonical_team_id = resolve_effective_team_id(team_id)
    row = TeamAEOConfig.objects.filter(team_id=canonical_team_id).first()
    return default_config() if row is None else _to_config(row)


def store_config(
    team_id: int,
    *,
    target_domains: list[str],
    brand_names: list[str],
    competitors: list[Competitor],
) -> AEOConfig:
    """Validate and replace the team's config.

    A stored row wins over every default, so a mis-keyed or empty payload would
    silently turn detection off from the next run. Reject it here instead.
    """
    domains = _clean_list(target_domains, "target_domains", MAX_TARGET_DOMAINS, _clean_domain)
    if not domains:
        raise AEOConfigError("target_domains must list at least one domain")
    names = _clean_list(brand_names, "brand_names", MAX_BRAND_NAMES, _clean_name) or list(_brand_names_from(domains))
    cleaned_competitors: list[dict[str, Any]] = []
    for competitor in competitors:
        name = _clean_name(competitor.name, "competitors[].name")
        if any(name.lower() == existing["name"].lower() for existing in cleaned_competitors):
            raise AEOConfigError(f"competitor {name!r} is listed more than once")
        competitor_domains = _clean_list(
            competitor.domains, f"competitors[{name!r}].domains", MAX_DOMAINS_PER_COMPETITOR, _clean_domain
        )
        cleaned_competitors.append({"name": name, "domains": competitor_domains})
    if len(cleaned_competitors) > MAX_COMPETITORS:
        raise AEOConfigError(f"competitors lists {len(cleaned_competitors)} entries; the limit is {MAX_COMPETITORS}")

    team = Team.objects.get(id=resolve_effective_team_id(team_id))
    row = get_or_create_team_extension(team, TeamAEOConfig)
    row.target_domains = domains
    row.brand_names = names
    row.competitors = cleaned_competitors
    row.save(update_fields=["target_domains", "brand_names", "competitors", "updated_at"])
    return _to_config(row)


def _brand_names_from(domains: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({(_DOMAIN_PARTS(domain).domain or domain).lower() for domain in domains}))


def _clean_list(values: Iterable[str], field: str, limit: int, clean: Callable[[str, str], str]) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        if not value or not value.strip():
            continue
        cleaned = clean(value, field)
        seen.setdefault(cleaned.lower(), cleaned)
    if len(seen) > limit:
        raise AEOConfigError(f"{field} lists {len(seen)} entries; the limit is {limit}")
    return list(seen.values())


def _clean_domain(value: str, field: str) -> str:
    domain = value.strip().lower()
    if len(domain) > GENERIC_VALUE_MAX_LEN or not _HOSTNAME_RE.match(domain):
        raise AEOConfigError(f"{field}: {value!r} is not a bare hostname (no scheme, path, port or spaces)")
    parts = _DOMAIN_PARTS(domain)
    if not parts.domain or not parts.suffix:
        raise AEOConfigError(f"{field}: {value!r} needs a registrable name and a public suffix, like example.com")
    return domain


def _clean_name(value: str, field: str) -> str:
    if len(value.strip()) > GENERIC_VALUE_MAX_LEN:
        raise AEOConfigError(f"{field}: a name is longer than {GENERIC_VALUE_MAX_LEN} characters")
    # Names are written to rows the alerting scout reads, so they get the same sanitization as engine text.
    name = sanitize_user_text(value, GENERIC_VALUE_MAX_LEN)
    if len(name) < MIN_NAME_LENGTH:
        raise AEOConfigError(f"{field}: {value!r} must be at least {MIN_NAME_LENGTH} characters")
    return name


def _to_config(row: TeamAEOConfig) -> AEOConfig:
    competitors = tuple(
        Competitor(name=str(item["name"]), domains=tuple(_strings(row, item.get("domains"), "competitors[].domains")))
        for item in _list(row, row.competitors, "competitors")
        if isinstance(item, dict) and item.get("name")
    )
    return AEOConfig(
        target_domains=tuple(_strings(row, row.target_domains, "target_domains")),
        brand_names=tuple(_strings(row, row.brand_names, "brand_names")),
        competitors=competitors,
    )


def _list(row: TeamAEOConfig, value: Any, field: str) -> list[Any]:
    if isinstance(value, list):
        return value
    # A string would iterate as characters; an empty list keeps the failure visible in the metrics and the log.
    logger.warning("aeo_config_field_not_a_list", team_id=row.team_id, field=field, value_type=type(value).__name__)
    return []


def _strings(row: TeamAEOConfig, value: Any, field: str) -> list[str]:
    return [item for item in _list(row, value, field) if isinstance(item, str) and item]

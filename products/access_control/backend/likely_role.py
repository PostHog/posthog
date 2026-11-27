from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from uuid import UUID

from posthog.dataclasses import frozen

from products.access_control.backend.facade.contracts import LikelyRole, RoleMatchSource

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_WRAPPER_WORDS = frozenset({"team", "teams", "squad", "group"})
_DOMAIN_SUFFIX_WORDS = frozenset({"eng", "engineering"})
_MIN_COMPACT_LENGTH = 3
_MIN_FUZZY_LENGTH = 4
_FUZZY_SCORE_FLOOR = 0.85


@frozen
class ParsedTeamIdentifier:
    organization: str | None
    slug: str


@frozen
class RoleCandidate:
    id: UUID
    name: str


@frozen
class ExternalReferenceCandidate:
    provider_organization_id: str
    provider_role_id: str
    provider_role_slug: str | None
    role_id: UUID
    role_name: str


@frozen
class _NormalizedText:
    full: str
    core: str
    compact: str
    domain: str


@frozen
class _NormalizedRole:
    candidate: RoleCandidate
    text: _NormalizedText


@frozen
class _ReferenceLookup:
    role: LikelyRole | None
    has_conflict: bool


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(value.lower()))


def _strip_affixes(words: tuple[str, ...], affixes: frozenset[str], *, strip_leading: bool) -> tuple[str, ...]:
    result = words
    if strip_leading and len(result) > 1 and result[0] in affixes:
        result = result[1:]
    if len(result) > 1 and result[-1] in affixes:
        result = result[:-1]
    return result


def _normalize_text(value: str) -> _NormalizedText:
    words = _tokens(value)
    core_words = _strip_affixes(words, _WRAPPER_WORDS, strip_leading=True)
    domain_words = _strip_affixes(core_words, _DOMAIN_SUFFIX_WORDS, strip_leading=False)
    return _NormalizedText(
        full=" ".join(words),
        core=" ".join(core_words),
        compact="".join(core_words),
        domain=" ".join(domain_words),
    )


def parse_team_identifier(team_name: str, *, default_organization: str | None = None) -> ParsedTeamIdentifier | None:
    stripped = team_name.strip()
    if not stripped:
        return None
    # Emails in CODEOWNERS carry '@' after the local part and name a person rather than a team.
    if "@" in stripped[1:]:
        return None

    without_at = stripped.lstrip("@").strip()
    if not without_at:
        return None

    if "/" in without_at:
        organization, _, slug = without_at.partition("/")
        organization = organization.strip().lower()
        slug = slug.strip().lower()
        if not organization or not slug or "/" in slug:
            return None
        return ParsedTeamIdentifier(organization=organization, slug=slug)

    slug = without_at.lower()
    if slug == "unowned":
        return None
    normalized_org = (
        default_organization.strip().lower() if default_organization and default_organization.strip() else None
    )
    return ParsedTeamIdentifier(organization=normalized_org, slug=slug)


class RoleMatcher:
    """Matches external team identifiers to an organization's PostHog roles.

    Explicit ``RoleExternalReference`` bindings always win over name similarity so an operator
    can override any heuristic match.
    """

    def __init__(
        self,
        *,
        references: Sequence[ExternalReferenceCandidate],
        roles: Sequence[RoleCandidate],
    ) -> None:
        self._references = tuple(references)
        self._roles = tuple(self._build_normalized_role(role) for role in roles)

    @staticmethod
    def _build_normalized_role(role: RoleCandidate) -> _NormalizedRole:
        return _NormalizedRole(candidate=role, text=_normalize_text(role.name))

    @staticmethod
    def _reference_matches_slug(reference: ExternalReferenceCandidate, slug: str) -> bool:
        if reference.provider_role_slug and reference.provider_role_slug.lower() == slug:
            return True
        return reference.provider_role_id.lower() == slug

    def _match_reference(self, parsed: ParsedTeamIdentifier) -> _ReferenceLookup:
        if parsed.organization is not None:
            for reference in self._references:
                if reference.provider_organization_id.lower() != parsed.organization:
                    continue
                if self._reference_matches_slug(reference, parsed.slug):
                    return _ReferenceLookup(
                        role=LikelyRole(
                            id=reference.role_id,
                            name=reference.role_name,
                            source=RoleMatchSource.EXTERNAL_REFERENCE,
                        ),
                        has_conflict=False,
                    )
            return _ReferenceLookup(role=None, has_conflict=False)

        matching_roles = {
            (reference.role_id, reference.role_name)
            for reference in self._references
            if self._reference_matches_slug(reference, parsed.slug)
        }
        if len(matching_roles) == 1:
            role_id, role_name = next(iter(matching_roles))
            return _ReferenceLookup(
                role=LikelyRole(id=role_id, name=role_name, source=RoleMatchSource.EXTERNAL_REFERENCE),
                has_conflict=False,
            )
        # Conflicting explicit mappings across different external orgs cannot be disambiguated without org context.
        if len(matching_roles) > 1:
            return _ReferenceLookup(role=None, has_conflict=True)
        return _ReferenceLookup(role=None, has_conflict=False)

    @staticmethod
    def _score_name(target: _NormalizedText, role: _NormalizedRole) -> float:
        role_text = role.text
        if not target.core or not role_text.core:
            return 0.0
        if target.full == role_text.full:
            return 1.0
        if target.core == role_text.core:
            return 0.95
        if len(target.compact) >= _MIN_COMPACT_LENGTH and target.compact == role_text.compact:
            return 0.93
        if min(len(target.domain), len(role_text.domain)) >= _MIN_COMPACT_LENGTH and target.domain == role_text.domain:
            return 0.90
        if min(len(target.core), len(role_text.core)) < _MIN_FUZZY_LENGTH:
            return 0.0
        ratio = SequenceMatcher(None, target.core, role_text.core).ratio()
        if ratio < _FUZZY_SCORE_FLOOR:
            return 0.0
        return _FUZZY_SCORE_FLOOR + 0.04 * ((ratio - _FUZZY_SCORE_FLOOR) / (1.0 - _FUZZY_SCORE_FLOOR))

    def match(self, team_name: str, *, default_organization: str | None = None) -> LikelyRole | None:
        parsed = parse_team_identifier(team_name, default_organization=default_organization)
        if parsed is None:
            return None

        lookup = self._match_reference(parsed)
        if lookup.role is not None or lookup.has_conflict:
            return lookup.role

        target = _normalize_text(parsed.slug)
        best_score = 0.0
        best_role: RoleCandidate | None = None
        tied = False
        for role in self._roles:
            score = self._score_name(target, role)
            if score < _FUZZY_SCORE_FLOOR:
                continue
            if score > best_score:
                best_score = score
                best_role = role.candidate
                tied = False
            elif score == best_score:
                tied = True

        if best_role is None or tied:
            return None
        return LikelyRole(id=best_role.id, name=best_role.name, source=RoleMatchSource.NAME_MATCH)

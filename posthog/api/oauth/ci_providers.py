"""The CI providers whose OIDC tokens PostHog can exchange for a project token.

Trust policy validation, the token exchange and the policy settings UI read providers only from
this registry, so no provider name or issuer appears anywhere else in the backend. A provider is
supported once it has an entry in `SUPPORTED_CI_PROVIDERS`. Providers we know we cannot support
are listed too, with the reason, so an error can name them.
"""

from __future__ import annotations

from enum import StrEnum

from posthog.dataclasses import frozen


class AudienceCheck(StrEnum):
    # The token's `aud` must equal this deployment's SITE_URL, which the CI job sets when it asks
    # its provider for the token. A token minted for another service is then never accepted.
    SITE_URL = "site_url"


@frozen
class CIClaimMapping:
    """Which claims of the provider's OIDC token carry each value a trust policy matches on, or
    an activity log entry records. A claim name of `None` means the provider has no such claim."""

    repository: str
    # Immutable: survives a rename, and a deleted repository re-created with the same name gets a
    # new one, so a policy pinned to it cannot be taken over by whoever claims the old name.
    repository_id: str
    ref: str | None
    environment: str | None
    workflow: str | None
    run_id: str | None
    sha: str | None


@frozen
class CIProvider:
    key: str
    name: str
    # Compared with the token's `iss` claim after trailing slashes are stripped from both.
    issuer: str
    jwks_url: str
    audience_check: AudienceCheck
    claims: CIClaimMapping
    # Formatted with the token's `repository` and `run_id` values to link an activity log entry
    # to its run, or `None` when the provider has no stable run URL.
    run_url_template: str | None
    docs_url: str


@frozen
class UnsupportedCIProvider:
    key: str
    name: str
    reason: str


SUPPORTED_CI_PROVIDERS: tuple[CIProvider, ...] = ()

UNSUPPORTED_CI_PROVIDERS: tuple[UnsupportedCIProvider, ...] = (
    UnsupportedCIProvider(
        key="bitbucket_pipelines",
        name="Bitbucket Pipelines",
        reason="The token's audience is fixed per workspace and cannot be set to this PostHog instance.",
    ),
    UnsupportedCIProvider(
        key="gitlab_self_managed",
        name="Self-managed GitLab",
        reason="Each instance is its own token issuer, and only the issuers listed here are trusted.",
    ),
)


def normalize_issuer(issuer: str) -> str:
    return issuer.rstrip("/")


def get_supported_ci_providers() -> tuple[CIProvider, ...]:
    return SUPPORTED_CI_PROVIDERS


def get_unsupported_ci_providers() -> tuple[UnsupportedCIProvider, ...]:
    return UNSUPPORTED_CI_PROVIDERS


def get_ci_provider_by_issuer(issuer: str) -> CIProvider | None:
    normalized = normalize_issuer(issuer)
    if not normalized:
        return None
    for provider in get_supported_ci_providers():
        if normalize_issuer(provider.issuer) == normalized:
            return provider
    return None


def get_ci_provider_by_key(key: str) -> CIProvider | None:
    for provider in get_supported_ci_providers():
        if provider.key == key:
            return provider
    return None

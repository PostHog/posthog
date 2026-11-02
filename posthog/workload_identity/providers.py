"""The workload providers whose OIDC tokens PostHog can exchange for a project token. Every provider
listed today is a CI provider.

Trust policy validation, the token exchange and the policy settings UI read providers only from
this registry, so no provider name or issuer appears anywhere else in the backend. A provider is
supported once it has an entry in `SUPPORTED_WORKLOAD_PROVIDERS`. Providers we know we cannot support
are listed too, with the reason, so an error can name them.
"""

from __future__ import annotations

from enum import StrEnum

from posthog.dataclasses import frozen


class AudienceCheck(StrEnum):
    # The token's `aud` must equal this deployment's SITE_URL, which the workload sets when it asks
    # its provider for the token. A token minted for another service is then never accepted.
    SITE_URL = "site_url"


@frozen
class WorkloadClaimMapping:
    """Which claims of the provider's OIDC token carry each value a trust policy matches on, or
    an activity log entry records. A claim name of `None` means the provider has no such claim."""

    repository: str
    ref: str | None
    environment: str | None
    workflow: str | None
    run_id: str | None
    sha: str | None


@frozen
class WorkloadProvider:
    key: str
    name: str
    # Compared with the token's `iss` claim after trailing slashes are stripped from both.
    issuer: str
    jwks_url: str
    audience_check: AudienceCheck
    # The claim every policy pins: the workload's immutable subject, the repository id for a CI provider.
    # It survives a rename, and a re-created repository gets a new one, so nobody can take over a policy
    # by claiming the old name.
    pinned_claim: str
    claims: WorkloadClaimMapping
    # How an activity log entry names the workload, formatted with the mapped claims, for example
    # "{repository} · {workflow} run {run_id}".
    actor_label_template: str
    # Formatted with the token's `repository` and `run_id` values to link an activity log entry
    # to its run, or `None` when the provider has no stable run URL.
    run_url_template: str | None
    docs_url: str


@frozen
class UnsupportedWorkloadProvider:
    key: str
    name: str
    reason: str


SUPPORTED_WORKLOAD_PROVIDERS: tuple[WorkloadProvider, ...] = ()

UNSUPPORTED_WORKLOAD_PROVIDERS: tuple[UnsupportedWorkloadProvider, ...] = (
    UnsupportedWorkloadProvider(
        key="bitbucket_pipelines",
        name="Bitbucket Pipelines",
        reason="The token's audience is fixed per workspace and cannot be set to this PostHog instance.",
    ),
    UnsupportedWorkloadProvider(
        key="gitlab_self_managed",
        name="Self-managed GitLab",
        reason="Each instance is its own token issuer, and only the issuers listed here are trusted.",
    ),
)


def normalize_issuer(issuer: str) -> str:
    return issuer.rstrip("/")


def get_supported_workload_providers() -> tuple[WorkloadProvider, ...]:
    return SUPPORTED_WORKLOAD_PROVIDERS


def get_unsupported_workload_providers() -> tuple[UnsupportedWorkloadProvider, ...]:
    return UNSUPPORTED_WORKLOAD_PROVIDERS


def get_workload_provider_by_issuer(issuer: str) -> WorkloadProvider | None:
    normalized = normalize_issuer(issuer)
    if not normalized:
        return None
    for provider in get_supported_workload_providers():
        if normalize_issuer(provider.issuer) == normalized:
            return provider
    return None


def get_workload_provider_by_key(key: str) -> WorkloadProvider | None:
    for provider in get_supported_workload_providers():
        if provider.key == key:
            return provider
    return None

"""The workload providers whose OIDC tokens PostHog can exchange for a project token.

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
class WorkloadClaim:
    """A claim of the provider's OIDC token, and how the UI names it."""

    name: str
    label: str
    help_text: str = ""


@frozen
class WorkloadProvider:
    key: str
    name: str
    # Compared with the token's `iss` claim after trailing slashes are stripped from both.
    issuer: str
    jwks_url: str
    audience_check: AudienceCheck
    # The claim every policy pins: the workload's immutable subject, for example a repository id. It
    # survives a rename, and a re-created workload gets a new one, so nobody can take over a policy by
    # claiming the old name.
    subject_claim: WorkloadClaim
    # The workload's human-readable name, for example a repository's full name. A policy pins it too,
    # so an admin approves the name they read.
    subject_name_claim: WorkloadClaim
    condition_claims: tuple[WorkloadClaim, ...]
    # The claims an activity log entry records and shows, read from the token at exchange time.
    recorded_claims: tuple[WorkloadClaim, ...]
    # How an activity log entry names the workload, formatted with the recorded claims, for example
    # "{repository} · {workflow} run {run_id}". A claim the token lacks formats as an empty string.
    actor_label_template: str
    # Formatted with the recorded claims to link an activity log entry to its run, or `None` when the
    # provider has no stable run URL.
    run_url_template: str | None
    docs_url: str

    def __post_init__(self) -> None:
        condition_names = [claim.name for claim in self.condition_claims]
        if len(set(condition_names)) != len(condition_names):
            raise ValueError(f"{self.key}: condition claims must be unique.")
        if {self.subject_claim.name, self.subject_name_claim.name} & set(condition_names):
            raise ValueError(f"{self.key}: the subject claims can't also be condition claims.")


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

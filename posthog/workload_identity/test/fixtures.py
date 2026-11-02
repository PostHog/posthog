from typing import TYPE_CHECKING

from unittest.mock import patch

from posthog.workload_identity.providers import AudienceCheck, WorkloadClaimMapping, WorkloadProvider

if TYPE_CHECKING:
    from unittest.mock import _patch

# Tests register this provider so they do not depend on which real providers the registry lists.
FAKE_WORKLOAD_ISSUER = "https://ci.example.com"

FAKE_WORKLOAD_PROVIDER = WorkloadProvider(
    key="fake_ci",
    name="Fake CI",
    issuer=FAKE_WORKLOAD_ISSUER,
    jwks_url="https://ci.example.com/.well-known/jwks",
    audience_check=AudienceCheck.SITE_URL,
    pinned_claim="repository_id",
    claims=WorkloadClaimMapping(
        repository="repository",
        ref="ref",
        environment="environment",
        workflow="workflow",
        run_id="run_id",
        sha="sha",
    ),
    actor_label_template="{repository} · {workflow} run {run_id}",
    run_url_template="https://ci.example.com/{repository}/runs/{run_id}",
    docs_url="https://example.com/docs/fake-ci",
)


def with_fake_workload_provider() -> "_patch[tuple[WorkloadProvider, ...]]":
    return patch("posthog.workload_identity.providers.SUPPORTED_WORKLOAD_PROVIDERS", (FAKE_WORKLOAD_PROVIDER,))

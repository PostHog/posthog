from typing import TYPE_CHECKING

from unittest.mock import patch

from posthog.workload_identity.providers import WorkloadClaim, WorkloadProvider

if TYPE_CHECKING:
    from unittest.mock import _patch

# Tests register this provider so they do not depend on which real providers the registry lists.
FAKE_WORKLOAD_ISSUER = "https://ci.example.com"

FAKE_WORKLOAD_PROVIDER = WorkloadProvider(
    key="fake_ci",
    name="Fake CI",
    issuer=FAKE_WORKLOAD_ISSUER,
    jwks_url="https://ci.example.com/.well-known/jwks",
    subject_claim=WorkloadClaim(name="repository_id", label="Repository ID"),
    subject_name_claim=WorkloadClaim(name="repository", label="Repository"),
    condition_claims=(
        WorkloadClaim(name="ref", label="Branch or tag", help_text="For example refs/heads/main."),
        WorkloadClaim(name="environment", label="Environment"),
    ),
    recorded_claims=(
        WorkloadClaim(name="repository", label="Repository"),
        WorkloadClaim(name="workflow", label="Workflow"),
        WorkloadClaim(name="run_id", label="Run"),
        WorkloadClaim(name="sha", label="Commit"),
        WorkloadClaim(name="ref", label="Branch or tag"),
        WorkloadClaim(name="environment", label="Environment"),
    ),
    actor_label_template="{repository} · {workflow} run {run_id}",
    run_url_template="https://ci.example.com/{repository}/runs/{run_id}",
    docs_url="https://example.com/docs/fake-ci",
)


def with_fake_workload_provider() -> "_patch[tuple[WorkloadProvider, ...]]":
    return patch("posthog.workload_identity.providers.SUPPORTED_WORKLOAD_PROVIDERS", (FAKE_WORKLOAD_PROVIDER,))

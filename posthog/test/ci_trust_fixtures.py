from typing import TYPE_CHECKING

from unittest.mock import patch

from posthog.api.oauth.ci_providers import AudienceCheck, CIClaimMapping, CIProvider

if TYPE_CHECKING:
    from unittest.mock import _patch

# Tests register this provider so they do not depend on which real providers the registry lists.
FAKE_CI_ISSUER = "https://ci.example.com"

FAKE_CI_PROVIDER = CIProvider(
    key="fake_ci",
    name="Fake CI",
    issuer=FAKE_CI_ISSUER,
    jwks_url="https://ci.example.com/.well-known/jwks",
    audience_check=AudienceCheck.SITE_URL,
    claims=CIClaimMapping(
        repository="repository",
        repository_id="repository_id",
        ref="ref",
        environment="environment",
        workflow="workflow",
        run_id="run_id",
        sha="sha",
    ),
    run_url_template="https://ci.example.com/{repository}/runs/{run_id}",
    docs_url="https://example.com/docs/fake-ci",
)


def with_fake_ci_provider() -> "_patch[tuple[CIProvider, ...]]":
    return patch("posthog.api.oauth.ci_providers.SUPPORTED_CI_PROVIDERS", (FAKE_CI_PROVIDER,))

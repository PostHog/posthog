import os

from django.conf import settings

# Placeholder secret used only during OpenAPI schema generation (find_enum_collisions /
# build:openapi-schema) when no real secret is configured — see build_openapi_mock_request. It lets
# the mock authenticate against a non-blank header instead of crashing the schema-gen command in
# prod-like environments where INTERNAL_API_SECRET defaults to empty. Never a valid secret at
# runtime: it is only accepted when OPENAPI_MOCK_INTERNAL_API_SECRET=1 (set solely by the schema-gen
# tooling) and no real secret is present.
OPENAPI_MOCK_INTERNAL_API_SECRET_PLACEHOLDER = "openapi-schema-generation-mock-secret"


def usable_internal_api_secrets() -> list[str]:
    """Internal API secrets accepted when authenticating service-to-service calls: the primary plus
    any still-trusted fallbacks (zero-downtime rotation), dropping empties. Values are
    whitespace-normalized at settings load (posthog/settings/data_stores.py), so this does not
    re-normalize per call.
    """
    secrets = [secret for secret in [settings.INTERNAL_API_SECRET, *settings.INTERNAL_API_SECRET_FALLBACKS] if secret]
    # Only when no real secret is configured and we're generating the OpenAPI schema: accept the
    # placeholder the mock injects, so schema-gen tooling works without INTERNAL_API_SECRET set.
    if not secrets and os.getenv("OPENAPI_MOCK_INTERNAL_API_SECRET") == "1":
        secrets.append(OPENAPI_MOCK_INTERNAL_API_SECRET_PLACEHOLDER)
    return secrets

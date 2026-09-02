import hashlib
import inspect
from collections.abc import Callable

from django.test import SimpleTestCase

from oauth2_provider import __version__ as installed_dot_version
from oauth2_provider.models import AbstractRefreshToken
from oauth2_provider.oauth2_validators import OAuth2Validator
from parameterized import parameterized

# OAuthValidator.validate_refresh_token (posthog/api/oauth/views.py) is a line-for-line fork
# of the upstream method with the reuse-protection family sweep replaced by
# revoke_oauth_token_family (posthog/models/oauth.py). That helper reproduces the effects of
# AbstractRefreshToken.revoke in bulk, and the sweep's correctness rests on how
# _create_refresh_token assigns token_family. Pinning the upstream sources makes a
# django-oauth-toolkit upgrade that touches any of them fail CI until the fork is
# re-reviewed, instead of shipping with silently stale semantics.
#
# Known hazards when moving to django-oauth-toolkit 3.4+:
# - validate_refresh_token looks tokens up by SHA-256 token_checksum; the token column
#   loses its unique index and is blank under hashed-at-rest storage, so the fork's
#   `token=` filter would lose its index or match nothing.
# - request.refresh_token is assigned the raw presented token, not rt.token.
# - RefreshToken.token becomes a TextField and the unique constraint moves to
#   (token_checksum, revoked); swapped models need a checksum backfill migration.
PINNED_UPSTREAM_SOURCES: list[tuple[str, Callable[..., object], str]] = [
    (
        "OAuth2Validator.validate_refresh_token",
        OAuth2Validator.validate_refresh_token,
        "2e4789d15b0f661fe79734d20e7b04e15b0eb9dc6446f4dbe14538a2deb8c66f",
    ),
    (
        "OAuth2Validator._create_refresh_token",
        OAuth2Validator._create_refresh_token,
        "f2d62a61db7fb44ce32a359311e18517e3936063a7615675543bec5f61b53991",
    ),
    (
        "AbstractRefreshToken.revoke",
        AbstractRefreshToken.revoke,
        "cee9cbb06e002042f3341e35ccb8dc39ffc72e2c7d2959d464362a6fbc999349",
    ),
]


class TestOAuthValidatorForkUpstreamPin(SimpleTestCase):
    @parameterized.expand(PINNED_UPSTREAM_SOURCES)
    def test_forked_upstream_source_is_unchanged(
        self, name: str, method: Callable[..., object], pinned_sha256: str
    ) -> None:
        actual_sha256 = hashlib.sha256(inspect.getsource(method).encode()).hexdigest()
        self.assertEqual(
            actual_sha256,
            pinned_sha256,
            f"django-oauth-toolkit {installed_dot_version} changed {name}, which "
            "OAuthValidator.validate_refresh_token (posthog/api/oauth/views.py) forks and "
            "revoke_oauth_token_family (posthog/models/oauth.py) reproduces in bulk. Diff "
            "the upstream method against the fork, port any behavior change (this file's "
            "header lists the known 3.4+ hazards), then update the pinned hash here.",
        )

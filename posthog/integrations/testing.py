"""Test helpers of the integrations SDK."""

from collections.abc import Iterator
from contextlib import contextmanager

from posthog.integrations.backend import use_backend
from posthog.integrations.backend.fake_backend import FakeBackend, TokenRefresher, no_token_refresher


@contextmanager
def fake_integrations_backend(*, token_refresher: TokenRefresher = no_token_refresher) -> Iterator[FakeBackend]:
    """Keep the integration rows in memory inside the block. Seed rows with `FakeBackend.seed`.

    with fake_integrations_backend() as backend:
        row = backend.seed(team_id=team.id, kind="slack", external_id="T1")
        assert IntegrationManager.slack.oauth.get(team.id, row.id) == row
    """
    backend = FakeBackend(token_refresher=token_refresher)
    with use_backend(backend):
        yield backend

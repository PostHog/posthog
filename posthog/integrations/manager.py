"""The entry point of the integrations SDK. Import the names from `posthog.integrations`, not from here.

    from posthog.integrations import IntegrationManager

    IntegrationManager.github.oauth.get(team_id, integration_id)  # one kind, one auth type: reads and writes
    IntegrationManager.stripe.any.list(team_id)                   # one kind, every auth type: reads and deletes
    IntegrationManager.any.get(team_id, integration_id)           # every kind: reads and deletes
    IntegrationManager.any.with_source_rows().delete(team_id, id) # every kind, warehouse source rows too
    IntegrationManager.source("ab-tasty").token.create(...)       # warehouse source rows of a registered kind

A kind class has an attribute only for the auth types that the kind supports, so mypy rejects
`IntegrationManager.github.credentials`. `.any` has no writes, because a new row has exactly one auth
type. See `posthog/integrations/README.md`.
"""

from collections.abc import Mapping

from posthog.integrations import accessors, source_kinds, usages
from posthog.integrations.enums import AuthType
from posthog.integrations.kinds_generated import GeneratedIntegrationManager

IntegrationReader = accessors.IntegrationReader
AuthAccessor = accessors.AuthAccessor
OAuthAccessor = accessors.OAuthAccessor
SourceKindAccessor = accessors.SourceKindAccessor
UsageProvider = usages.UsageProvider

IntegrationManager = GeneratedIntegrationManager()


def register_source_kinds(kinds: Mapping[str, AuthType]) -> None:
    """Register warehouse source kinds and the default auth type of each. Call it from `AppConfig.ready`."""
    source_kinds.register_source_kinds(kinds)


def register_usage_provider(provider: UsageProvider) -> None:
    """Add a provider for `usages`. A product adds `backend/integration_usages.py` instead."""
    usages.register_usage_provider(provider)

"""Linked accounts settings API (``/api/users/@me/linked_accounts``).

This route is retained for backwards compatibility. It uses the same view
implementation as :mod:`posthog.api.user_integration` (personal GitHub
integrations under ``/api/users/@me/integrations``).
"""

from posthog.api.user_integration import UserIntegrationViewSet as LinkedAccountsViewSet

__all__ = ["LinkedAccountsViewSet"]

"""Facade re-export for the customer_analytics team-extension model.

Core's ``Team.customer_analytics_config`` accessor and ``posthog/api/team.py``
register/read this extension by class identity through
``get_or_create_team_extension``. Re-exporting the model class keeps that
registry coupling at the facade boundary without exposing the internal models
package.
"""

from products.customer_analytics.backend.models.team_customer_analytics_config import TeamCustomerAnalyticsConfig

__all__ = ["TeamCustomerAnalyticsConfig"]

"""The work of the foreign keys to integration rows. The integrations SDK loads this module."""

from posthog.integrations import IntegrationRecord

from products.data_modeling.backend.models import GitHubSyncConfig


def before_integration_delete(row: IntegrationRecord) -> None:
    GitHubSyncConfig.objects.filter(team_id=row.team_id, integration_id=row.id).update(integration=None)

"""The work of the foreign keys to integration rows. The integrations SDK loads this module."""

from posthog.integrations import IntegrationRecord

from products.customer_analytics.backend.models import EventStream, FeatureRequestGitHubLink


def before_integration_delete(row: IntegrationRecord) -> None:
    EventStream.objects.for_team(row.team_id).filter(slack_integration_id=row.id).update(slack_integration=None)
    FeatureRequestGitHubLink.objects.for_team(row.team_id).filter(integration_id=row.id).update(integration=None)

"""The work of the foreign keys to integration rows. The integrations SDK loads this module."""

from posthog.integrations import IntegrationRecord

from products.batch_exports.backend.models import BatchExportDestination


def before_integration_delete(row: IntegrationRecord) -> None:
    BatchExportDestination.objects.filter(integration_id=row.id).update(integration=None)

"""The batch exports that write through an integration row. The integrations SDK loads this module."""

from products.batch_exports.backend.facade.api import list_batch_exports_using_integration
from products.integrations.backend.facade.contracts import IntegrationUsage

BATCH_EXPORT_USAGE_TYPE = "batch_export"


def integration_usages(team_id: int, integration_id: int) -> list[IntegrationUsage]:
    return [
        IntegrationUsage(type=BATCH_EXPORT_USAGE_TYPE, id=str(export.id), name=export.name or str(export.id))
        for export in list_batch_exports_using_integration(team_id=team_id, integration_id=integration_id)
    ]

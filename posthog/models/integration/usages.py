"""The PostHog objects that use one `Integration` row.

One row can serve several products: an OAuth grant, an installation or typed-in credentials. Code
that deletes or edits a row asks this module first, so the check is the same everywhere.

`posthog/models/integration/__init__.py` does not import this module, because the product facades
that it calls import the integration models.
"""

from enum import StrEnum

from posthog.dataclasses import frozen

from products.batch_exports.backend.facade.api import list_batch_exports_using_integration
from products.cdp.backend.services.integration_usage import get_enabled_hog_functions_using_integration
from products.warehouse_sources.backend.facade.integration_references import list_sources_using_integration
from products.workflows.backend.facade.api import get_active_workflows_using_integration


class IntegrationUsageType(StrEnum):
    WAREHOUSE_SOURCE = "warehouse_source"
    WORKFLOW = "workflow"
    HOG_FUNCTION = "hog_function"
    BATCH_EXPORT = "batch_export"


@frozen
class IntegrationUsage:
    type: IntegrationUsageType
    id: str
    name: str


def integration_usages(team_id: int, integration_pk: int) -> list[IntegrationUsage]:
    """Every live object of the team that uses the row: warehouse sources, active workflows, enabled
    hog functions and batch exports. Sorted by type, then name."""
    usages = [
        IntegrationUsage(
            type=IntegrationUsageType.WAREHOUSE_SOURCE,
            id=str(source.id),
            name=f"{source.source_type} ({source.prefix})" if source.prefix else source.source_type,
        )
        for source in list_sources_using_integration(team_id=team_id, integration_pk=integration_pk)
    ]
    usages += [
        IntegrationUsage(type=IntegrationUsageType.WORKFLOW, id=str(flow.id), name=flow.name or str(flow.id))
        for flow in get_active_workflows_using_integration(team_id=team_id, integration_id=integration_pk)
    ]
    usages += [
        IntegrationUsage(
            type=IntegrationUsageType.HOG_FUNCTION, id=str(function.id), name=function.name or str(function.id)
        )
        for function in get_enabled_hog_functions_using_integration(team_id=team_id, integration_id=integration_pk)
    ]
    usages += [
        IntegrationUsage(
            type=IntegrationUsageType.BATCH_EXPORT,
            id=str(batch_export.id),
            name=batch_export.name or str(batch_export.id),
        )
        for batch_export in list_batch_exports_using_integration(team_id=team_id, integration_id=integration_pk)
    ]
    order = list(IntegrationUsageType)
    return sorted(usages, key=lambda usage: (order.index(usage.type), usage.name))

"""Re-export surface for dashboard widget OpenAPI serializers.

Typed widget PATCH/batch/catalog schemas are built in ``widget_specs/openapi.py``
from Pydantic config models. This module keeps ``dashboard.api`` and spectacular
registration imports stable without reaching into ``widget_specs`` from the API
package.
"""

from products.dashboards.backend.widget_specs.openapi import (
    WIDGET_BATCH_ADD_OPENAPI_HELP,
    WIDGET_CONFIG_SERIALIZERS,
    AddDashboardWidgetRequestOpenApi,
    DashboardPatchTileOpenApiSerializer,
    DashboardPatchWidgetOpenApiSerializer,
    DashboardWidgetConfigField,
    DashboardWidgetConfigOpenApi,
    PatchedDashboardOpenApiSerializer,
    UpdateDashboardWidgetRequestOpenApi,
    WidgetCatalogEntryOpenApi,
    WidgetCatalogResponseSerializer,
)

__all__ = [
    "AddDashboardWidgetRequestOpenApi",
    "DashboardPatchTileOpenApiSerializer",
    "DashboardPatchWidgetOpenApiSerializer",
    "DashboardWidgetConfigField",
    "DashboardWidgetConfigOpenApi",
    "PatchedDashboardOpenApiSerializer",
    "UpdateDashboardWidgetRequestOpenApi",
    "WidgetCatalogEntryOpenApi",
    "WidgetCatalogResponseSerializer",
    "WIDGET_BATCH_ADD_OPENAPI_HELP",
    "WIDGET_CONFIG_SERIALIZERS",
    *[serializer.__name__ for serializer in WIDGET_CONFIG_SERIALIZERS.values()],
]

for _serializer in WIDGET_CONFIG_SERIALIZERS.values():
    globals()[_serializer.__name__] = _serializer

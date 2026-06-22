from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import GoogleWorkspaceAdminReportsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleWorkspaceAdminReportsSource(SimpleSource[GoogleWorkspaceAdminReportsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEWORKSPACEADMINREPORTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_WORKSPACE_ADMIN_REPORTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Workspace Admin Reports",
            iconPath="/static/services/google_workspace_admin_reports.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldOauthConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import QuickBooksSourceConfig
from posthog.temporal.data_imports.sources.quickbooks.settings import (
    ENDPOINTS as QUICKBOOKS_ENDPOINTS,
    INCREMENTAL_FIELDS as QUICKBOOKS_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.sources.quickbooks.quickbooks import (
    QuickBooksPermissionError,
    quickbooks_source,
    validate_credentials as validate_quickbooks_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class QuickBooksSource(SimpleSource[QuickBooksSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUICKBOOKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.QUICK_BOOKS,
            caption="""Connect your QuickBooks account to automatically sync your accounting data into the PostHog Data warehouse.

QuickBooks Online provides comprehensive financial data including invoices, payments, customers, vendors, and more.

To connect:
1. Click "Connect with QuickBooks" below
2. Sign in to your QuickBooks account
3. Authorize PostHog to access your QuickBooks data

**Required permissions**: Read access to your QuickBooks accounting data (scope: `com.intuit.quickbooks.accounting`)

**Note**: This connector supports QuickBooks Online. QuickBooks Desktop is not currently supported.
""",
            iconPath="/static/services/quickbooks.jpg",
            docsUrl="https://posthog.com/docs/cdp/sources/quickbooks",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="oauth_integration",
                        label="QuickBooks integration",
                        kind="quickbooks",
                        required=True,
                    ),
                ],
            ),
            featureFlag="dwh_quickbooks",
        )

    def get_schemas(
        self, config: QuickBooksSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=QUICKBOOKS_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in QUICKBOOKS_ENDPOINTS
        ]

    def validate_credentials(self, config: QuickBooksSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            integration = self.get_oauth_integration(config.oauth_integration, team_id)
            access_token = integration.access_token
            realm_id = integration.config.get("realmId")

            if not realm_id:
                return False, "QuickBooks realm ID not found in integration config"

            if validate_quickbooks_credentials(access_token, realm_id):
                return True, None
            else:
                return False, "Invalid QuickBooks credentials"
        except QuickBooksPermissionError as e:
            missing_resources = ", ".join(e.missing_permissions.keys())
            return False, f"QuickBooks access token lacks permissions for {missing_resources}"
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: QuickBooksSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.oauth_integration, inputs.team_id)
        access_token = integration.access_token
        realm_id = integration.config.get("realmId")

        if not realm_id:
            raise ValueError("QuickBooks realm ID not found in integration config")

        return quickbooks_source(
            access_token=access_token,
            realm_id=realm_id,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
            job=inputs.job,
        )

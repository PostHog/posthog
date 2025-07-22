import re
from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.chargebee import (
    validate_credentials as validate_chargebee_credentials,
)
from posthog.temporal.data_imports.pipelines.chargebee.settings import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import ChargebeeSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class ChargebeeSource(BaseSource[ChargebeeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.CHARGEBEE

    def get_schemas(self, config: ChargebeeSourceConfig) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def validate_credentials(self, config: ChargebeeSourceConfig) -> tuple[bool, str | None]:
        subdomain_regex = re.compile("^[a-zA-Z-]+$")
        if not subdomain_regex.match(config.site_name):
            return False, "Chargebee site name is incorrect"

        if validate_chargebee_credentials(config.api_key, config.site_name):
            return True, None

        return False, "Invalid credentials"

    def source_for_pipeline(self, config: ChargebeeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # TODO: Move the Chargebee source func in here
        return SourceResponse(name="", items=iter([]), primary_keys=None)

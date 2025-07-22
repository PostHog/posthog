import re
from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.vitally import (
    validate_credentials as validate_vitally_credentials,
)
from posthog.temporal.data_imports.pipelines.vitally.settings import (
    ENDPOINTS as VITALLY_ENDPOINTS,
    INCREMENTAL_FIELDS as VITALLY_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import VitallySourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class VitallySource(BaseSource[VitallySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.VITALLY

    def get_schemas(self, config: VitallySourceConfig) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=VITALLY_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=VITALLY_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=VITALLY_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in VITALLY_ENDPOINTS
        ]

    def validate_credentials(self, config: VitallySourceConfig) -> tuple[bool, str | None]:
        subdomain_regex = re.compile("^[a-zA-Z-]+$")
        if config.region.selection == "US" and not subdomain_regex.match(config.region.subdomain):
            return False, "Vitally subdomain is incorrect"

        if validate_vitally_credentials(config.secret_token, config.region.selection, config.region.subdomain):
            return True, None

        return False, "Invalid credentials"

    def source_for_pipeline(self, config: VitallySourceConfig, inputs: SourceInputs) -> SourceResponse:
        # TODO: Move the Vitally source func in here
        return SourceResponse(name="", items=iter([]), primary_keys=None)

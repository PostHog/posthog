from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import CustomerIOSourceConfig
from posthog.warehouse.types import ExternalDataSourceType

# TODO(Andrew J. McGehee): implement the source logic for CustomerIOSource


@SourceRegistry.register
class CustomerIOSource(BaseSource[CustomerIOSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CUSTOMERIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CUSTOMER_IO,
            iconPath="/static/services/customer-io.png",
            caption=None,  # only needed if you want to inline docs
            docsUrl=None,  # TODO(Andrew J. McGehee): link to the docs in the website, full path including https://
            fields=cast(list[FieldType], []),  # TODO(Andrew J. McGehee): add source config fields here
            unreleasedSource=True,
        )

    def validate_credentials(self, config: CustomerIOSourceConfig, team_id: int) -> tuple[bool, str | None]:
        # TODO(Andrew J. McGehee): implement the logic to validate the credentials of your source,
        # e.g. check the validity of API keys. returns a tuple of whether the credentials are valid,
        # and if not, returns an error message to return to the user
        raise NotImplementedError()

    def get_schemas(
        self, config: CustomerIOSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        raise NotImplementedError()

    def source_for_pipeline(self, config: CustomerIOSourceConfig, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError()

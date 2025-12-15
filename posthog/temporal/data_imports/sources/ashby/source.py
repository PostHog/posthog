from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import AshbySourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType

# TODO(Andrew J. McGehee): implement the source logic for AshbySource


@SourceRegistry.register
class AshbySource(SimpleSource[AshbySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ASHBY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ASHBY,
            iconPath="/static/services/ashby.png",
            label="Ashby",  # only needed if the readable name is complex. delete otherwise
            caption=None,  # only needed if you want to inline docs
            docsUrl=None,  # TODO(Andrew J. McGehee): link to the docs in the website, full path including https://
            fields=cast(list[FieldType], []),  # TODO(Andrew J. McGehee): add source config fields here
            unreleasedSource=True,
        )

    def validate_credentials(self, config: AshbySourceConfig, team_id: int) -> tuple[bool, str | None]:
        # TODO(Andrew J. McGehee): implement the logic to validate the credentials of your source,
        # e.g. check the validity of API keys. returns a tuple of whether the credentials are valid,
        # and if not, returns an error message to return to the user
        raise NotImplementedError()

    def get_schemas(self, config: AshbySourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        raise NotImplementedError()

    def source_for_pipeline(self, config: AshbySourceConfig, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError()

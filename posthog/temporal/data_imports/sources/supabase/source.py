from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import SupabaseSourceConfig
from posthog.temporal.data_imports.sources.postgres.source import PostgresSource
from posthog.warehouse.types import ExternalDataSourceType

postgres = PostgresSource()


@SourceRegistry.register
class SupabaseSource(BaseSource[SupabaseSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    source_name = "Supabase"  # used in error logs to differentiate this from postgres source

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SUPABASE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SUPABASE,
            iconPath="/static/services/supabase.png",
            caption="Enter your Supabase credentials to automatically pull your data into the PostHog Data warehouse",
            docsUrl="https://posthog.com/tutorials/supabase-query",
            fields=postgres.get_source_config.fields,
            betaSource=True,
            featureFlag="supabase-dwh",
        )

    def validate_credentials(self, config: SupabaseSourceConfig, team_id: int) -> tuple[bool, str | None]:
        return postgres.validate_credentials(config, team_id)

    def get_schemas(self, config: SupabaseSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return postgres.get_schemas(config, team_id, with_counts)

    def source_for_pipeline(self, config: SupabaseSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return postgres.source_for_pipeline(config, inputs)

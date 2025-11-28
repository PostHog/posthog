from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import PostgresSourceConfig, SupabaseSourceConfig
from posthog.temporal.data_imports.sources.postgres.source import PostgresSource

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SupabaseSource(PostgresSource):
    def __init__(self):
        super().__init__(source_name="Supabase")

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
            fields=super().get_source_config.fields,
            betaSource=True,
            featureFlag="supabase-dwh",
        )

    def _postgres_source_config(self, config: SupabaseSourceConfig) -> PostgresSourceConfig:
        return PostgresSourceConfig(**config.__dict__)

    def validate_credentials(self, config: SupabaseSourceConfig, team_id: int) -> tuple[bool, str | None]:  # type: ignore[override]
        pg_config = self._postgres_source_config(config)
        return super().validate_credentials(pg_config, team_id)

    def get_schemas(self, config: SupabaseSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:  # type: ignore[override]
        pg_config = self._postgres_source_config(config)
        return super().get_schemas(pg_config, team_id, with_counts)

    def source_for_pipeline(self, config: SupabaseSourceConfig, inputs: SourceInputs) -> SourceResponse:  # type: ignore[override]
        pg_config = self._postgres_source_config(config)
        return super().source_for_pipeline(pg_config, inputs)

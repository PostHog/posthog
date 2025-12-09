from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
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

from posthog.temporal.data_imports.sources.generated_configs import BigQuerySourceConfig
from posthog.warehouse.models import ExternalDataSource
from posthog.temporal.data_imports.sources import SourceRegistry


def test_bigquery_get_schemas():
    source_cls = SourceRegistry.get_source(ExternalDataSource.Type.BIGQUERY)
    source_cls.get_schemas(BigQuerySourceConfig(), 1)

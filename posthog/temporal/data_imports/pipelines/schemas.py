from posthog.warehouse.models import ExternalDataSource
from posthog.temporal.data_imports.pipelines.stripe.settings import ALL_ENDPOINTS, DEFAULT_ENDPOINTS

PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING = {ExternalDataSource.Type.STRIPE: DEFAULT_ENDPOINTS}
PIPELINE_TYPE_SCHEMA_MAPPING = {ExternalDataSource.Type.STRIPE: ALL_ENDPOINTS}

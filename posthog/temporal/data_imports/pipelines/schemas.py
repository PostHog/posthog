from posthog.warehouse.models import ExternalDataSource
from posthog.temporal.data_imports.pipelines.stripe.settings import ENDPOINTS

PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING = {ExternalDataSource.Type.STRIPE: ENDPOINTS}

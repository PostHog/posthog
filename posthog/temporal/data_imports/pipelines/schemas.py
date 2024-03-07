from posthog.warehouse.models import ExternalDataSource
from posthog.temporal.data_imports.pipelines.stripe.settings import ENDPOINTS as STRIPE_ENDPOINTS
from posthog.temporal.data_imports.pipelines.hubspot.settings import ENDPOINTS as HUBSPOT_ENDPOINTS

PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING = {
    ExternalDataSource.Type.STRIPE: STRIPE_ENDPOINTS,
    ExternalDataSource.Type.HUBSPOT: HUBSPOT_ENDPOINTS,
    ExternalDataSource.Type.POSTGRES: (),
}

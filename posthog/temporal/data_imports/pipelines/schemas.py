from posthog.temporal.data_imports.pipelines.zendesk.settings import BASE_ENDPOINTS, SUPPORT_ENDPOINTS
from posthog.warehouse.models import ExternalDataSource
from posthog.temporal.data_imports.pipelines.stripe.settings import (
    ENDPOINTS as STRIPE_ENDPOINTS,
    INCREMENTAL_ENDPOINTS as STRIPE_INCREMENTAL_ENDPOINTS,
)
from posthog.temporal.data_imports.pipelines.hubspot.settings import ENDPOINTS as HUBSPOT_ENDPOINTS

PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING = {
    ExternalDataSource.Type.STRIPE: STRIPE_ENDPOINTS,
    ExternalDataSource.Type.HUBSPOT: HUBSPOT_ENDPOINTS,
    ExternalDataSource.Type.ZENDESK: tuple(
        list(BASE_ENDPOINTS) + [resource for resource, endpoint_url, data_key, cursor_paginated in SUPPORT_ENDPOINTS]
    ),
    ExternalDataSource.Type.POSTGRES: (),
}

PIPELINE_TYPE_INCREMENTAL_ENDPOINTS_MAPPING = {
    ExternalDataSource.Type.STRIPE: STRIPE_INCREMENTAL_ENDPOINTS,
    ExternalDataSource.Type.HUBSPOT: (),
    ExternalDataSource.Type.ZENDESK: (),
    ExternalDataSource.Type.POSTGRES: (),
}

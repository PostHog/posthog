from posthog.temporal.data_imports.pipelines.chargebee.settings import (
    ENDPOINTS as CHARGEBEE_ENDPOINTS,
    INCREMENTAL_ENDPOINTS as CHARGEBEE_INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS as CHARGEBEE_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.pipelines.hubspot.settings import (
    ENDPOINTS as HUBSPOT_ENDPOINTS,
)
from posthog.temporal.data_imports.pipelines.salesforce.settings import (
    ENDPOINTS as SALESFORCE_ENDPOINTS,
    INCREMENTAL_ENDPOINTS as SALESFORCE_INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS as SALESFORCE_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.pipelines.stripe.settings import (
    ENDPOINTS as STRIPE_ENDPOINTS,
    INCREMENTAL_ENDPOINTS as STRIPE_INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS as STRIPE_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.pipelines.vitally.settings import (
    ENDPOINTS as VITALLY_ENDPOINTS,
    INCREMENTAL_ENDPOINTS as VITALLY_INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS as VITALLY_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.pipelines.zendesk.settings import (
    BASE_ENDPOINTS,
    INCREMENTAL_ENDPOINTS as ZENDESK_INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS as ZENDESK_INCREMENTAL_FIELDS,
    SUPPORT_ENDPOINTS,
)
from posthog.temporal.data_imports.pipelines.temporalio.source import (
    ENDPOINTS as TEMPORALIO_ENDPOINTS,
    INCREMENTAL_ENDPOINTS as TEMPORALIO_INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS as TEMPORALIO_INCREMENTAL_FIELDS,
)

from posthog.warehouse.models import ExternalDataSource
from posthog.warehouse.types import IncrementalField

PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING = {
    ExternalDataSource.Type.STRIPE: STRIPE_ENDPOINTS,
    ExternalDataSource.Type.HUBSPOT: HUBSPOT_ENDPOINTS,
    ExternalDataSource.Type.ZENDESK: tuple(
        list(BASE_ENDPOINTS) + [resource for resource, endpoint_url, data_key, cursor_paginated in SUPPORT_ENDPOINTS]
    ),
    ExternalDataSource.Type.POSTGRES: (),
    ExternalDataSource.Type.SNOWFLAKE: (),
    ExternalDataSource.Type.SALESFORCE: SALESFORCE_ENDPOINTS,
    ExternalDataSource.Type.MYSQL: (),
    ExternalDataSource.Type.MSSQL: (),
    ExternalDataSource.Type.VITALLY: VITALLY_ENDPOINTS,
    ExternalDataSource.Type.BIGQUERY: (),
    ExternalDataSource.Type.CHARGEBEE: CHARGEBEE_ENDPOINTS,
    ExternalDataSource.Type.GOOGLEADS: (),
    ExternalDataSource.Type.TEMPORALIO: TEMPORALIO_ENDPOINTS,
    ExternalDataSource.Type.DOIT: (),
    ExternalDataSource.Type.MONGODB: (),
    ExternalDataSource.Type.GOOGLESHEETS: (),
}

PIPELINE_TYPE_INCREMENTAL_ENDPOINTS_MAPPING = {
    ExternalDataSource.Type.STRIPE: STRIPE_INCREMENTAL_ENDPOINTS,
    ExternalDataSource.Type.HUBSPOT: (),
    ExternalDataSource.Type.ZENDESK: ZENDESK_INCREMENTAL_ENDPOINTS,
    ExternalDataSource.Type.POSTGRES: (),
    ExternalDataSource.Type.SNOWFLAKE: (),
    ExternalDataSource.Type.SALESFORCE: SALESFORCE_INCREMENTAL_ENDPOINTS,
    ExternalDataSource.Type.MYSQL: (),
    ExternalDataSource.Type.MSSQL: (),
    ExternalDataSource.Type.VITALLY: VITALLY_INCREMENTAL_ENDPOINTS,
    ExternalDataSource.Type.BIGQUERY: (),
    ExternalDataSource.Type.CHARGEBEE: CHARGEBEE_INCREMENTAL_ENDPOINTS,
    ExternalDataSource.Type.GOOGLEADS: (),
    ExternalDataSource.Type.TEMPORALIO: TEMPORALIO_INCREMENTAL_ENDPOINTS,
    ExternalDataSource.Type.DOIT: (),
    ExternalDataSource.Type.MONGODB: (),
    ExternalDataSource.Type.GOOGLESHEETS: (),
}

PIPELINE_TYPE_INCREMENTAL_FIELDS_MAPPING: dict[ExternalDataSource.Type, dict[str, list[IncrementalField]]] = {
    ExternalDataSource.Type.STRIPE: STRIPE_INCREMENTAL_FIELDS,
    ExternalDataSource.Type.HUBSPOT: {},
    ExternalDataSource.Type.ZENDESK: ZENDESK_INCREMENTAL_FIELDS,
    ExternalDataSource.Type.POSTGRES: {},
    ExternalDataSource.Type.SNOWFLAKE: {},
    ExternalDataSource.Type.SALESFORCE: SALESFORCE_INCREMENTAL_FIELDS,
    ExternalDataSource.Type.MYSQL: {},
    ExternalDataSource.Type.MSSQL: {},
    ExternalDataSource.Type.VITALLY: VITALLY_INCREMENTAL_FIELDS,
    ExternalDataSource.Type.BIGQUERY: {},
    ExternalDataSource.Type.CHARGEBEE: CHARGEBEE_INCREMENTAL_FIELDS,
    ExternalDataSource.Type.GOOGLEADS: {},
    ExternalDataSource.Type.TEMPORALIO: TEMPORALIO_INCREMENTAL_FIELDS,
    ExternalDataSource.Type.DOIT: {},
    ExternalDataSource.Type.MONGODB: {},
    ExternalDataSource.Type.GOOGLESHEETS: {},
}

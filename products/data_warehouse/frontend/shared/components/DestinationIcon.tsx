import { Tooltip } from 'lib/lemon-ui/Tooltip'

import IconPostHog from 'public/posthog-icon.svg'
import IconS3 from 'public/services/aws-s3.png'
import IconAzureBlob from 'public/services/azure-blob-storage.png'
import IconBigQuery from 'public/services/bigquery.png'
import IconDatabricks from 'public/services/databricks.png'
import IconPostgres from 'public/services/postgres.png'
import IconRedshift from 'public/services/redshift.png'
import IconSnowflake from 'public/services/snowflake.png'

import { ExternalDataDestinationTypeEnumApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

// The same artwork batch exports uses for its destinations, so one warehouse shows the same logo
// wherever a PostHog surface names it. Keyed off this product's own enum rather than shared with
// `BATCH_EXPORT_ICON_MAP`, because the two enums spell S3 differently.
const DESTINATION_ICON_MAP: Record<ExternalDataDestinationTypeEnumApi, string> = {
    PostHogWarehouse: IconPostHog,
    Postgres: IconPostgres,
    Redshift: IconRedshift,
    Snowflake: IconSnowflake,
    BigQuery: IconBigQuery,
    Databricks: IconDatabricks,
    AzureBlob: IconAzureBlob,
    S3: IconS3,
}

const DESTINATION_TYPE_LABELS: Record<ExternalDataDestinationTypeEnumApi, string> = {
    PostHogWarehouse: 'PostHog warehouse',
    Postgres: 'Postgres',
    Redshift: 'Redshift',
    Snowflake: 'Snowflake',
    BigQuery: 'BigQuery',
    Databricks: 'Databricks',
    AzureBlob: 'Azure Blob',
    S3: 'S3',
}

/** The label a person should see for a destination type. The API serializes the raw enum value. */
export function destinationTypeLabel(type: ExternalDataDestinationTypeEnumApi): string {
    return DESTINATION_TYPE_LABELS[type] ?? type
}

export interface DestinationIconProps {
    type: ExternalDataDestinationTypeEnumApi
    size?: 'small' | 'medium'
}

export function DestinationIcon({ type, size = 'small' }: DestinationIconProps): JSX.Element {
    const label = destinationTypeLabel(type)

    return (
        <Tooltip title={label}>
            {/* Fixed box, natural aspect: the service marks are square but PostHog's is a wide
                wordmark, and forcing it square squashes it. */}
            <span className={`flex items-center justify-center ${size === 'small' ? 'size-8' : 'size-11'}`}>
                <img src={DESTINATION_ICON_MAP[type]} alt={label} className="max-w-full max-h-full" />
            </span>
        </Tooltip>
    )
}

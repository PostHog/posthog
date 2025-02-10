import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import BlushingHog from 'public/hedgehog/blushing-hog.png'
import IconAwsS3 from 'public/services/aws-s3.png'
import Iconazure from 'public/services/azure.png'
import IconBigQuery from 'public/services/bigquery.png'
import IconChargebee from 'public/services/chargebee.png'
import IconCloudflare from 'public/services/cloudflare.png'
import IconGoogleCloudStorage from 'public/services/google-cloud-storage.png'
import IconHubspot from 'public/services/hubspot.png'
import IconMySQL from 'public/services/mysql.png'
import IconPostgres from 'public/services/postgres.png'
import IconSalesforce from 'public/services/salesforce.png'
import IconSnowflake from 'public/services/snowflake.png'
import IconMSSQL from 'public/services/sql-azure.png'
import IconStripe from 'public/services/stripe.png'
import IconVitally from 'public/services/vitally.png'
import IconZendesk from 'public/services/zendesk.png'
import { getDataWarehouseSourceUrl } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'

/**
 * In some cases we don't have the backend telling us what provider we have for blob storage, so we can have some
 * heuristic to guess, then fallback to a shrugging hedgehog.
 * @param url
 */
export function mapUrlToProvider(url: string): string {
    if (url.includes('.s3.amazonaws.com')) {
        return 'aws'
    } else if (url.startsWith('https://storage.googleapis.com')) {
        return 'google-cloud'
    } else if (url.includes('.blob.')) {
        return 'azure'
    } else if (url.includes('.r2.cloudflarestorage.com')) {
        return 'cloudflare-r2'
    }
    return 'BlushingHog'
}

/**
 * DataWarehouseSourceIcon component to render an icon
 * @param type
 * @param size
 */
export function DataWarehouseSourceIcon({
    type,
    size = 'small',
}: {
    type: string
    size?: 'small' | 'medium'
}): JSX.Element {
    const sizePx = size === 'small' ? 30 : 60

    const icon = {
        Stripe: IconStripe,
        Hubspot: IconHubspot,
        Zendesk: IconZendesk,
        Postgres: IconPostgres,
        MySQL: IconMySQL,
        Snowflake: IconSnowflake,
        aws: IconAwsS3,
        'google-cloud': IconGoogleCloudStorage,
        'cloudflare-r2': IconCloudflare,
        azure: Iconazure,
        Salesforce: IconSalesforce,
        MSSQL: IconMSSQL,
        Vitally: IconVitally,
        BigQuery: IconBigQuery,
        Chargebee: IconChargebee,
        BlushingHog: BlushingHog, // fallback, we don't know what this is
    }[type]

    return (
        <div className="flex items-center gap-4">
            <Tooltip
                title={
                    <>
                        {type}
                        <br />
                        Click to view docs
                    </>
                }
            >
                <Link to={getDataWarehouseSourceUrl(type)}>
                    <img
                        src={icon}
                        alt={type}
                        height={sizePx}
                        width={sizePx}
                        className="rounded object-contain max-w-none"
                    />
                </Link>
            </Tooltip>
        </div>
    )
}

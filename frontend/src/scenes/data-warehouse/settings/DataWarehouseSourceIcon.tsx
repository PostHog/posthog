import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import BlushingHog from 'public/hedgehog/blushing-hog.png'
import IconPostHog from 'public/posthog-icon.svg'
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
    if (url.includes('amazonaws.com')) {
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

const SIZE_PX_MAP = {
    xsmall: 16,
    small: 30,
    medium: 60,
}

export function DataWarehouseSourceIcon({
    type,
    size = 'small',
    sizePx: sizePxProps,
    disableTooltip = false,
}: {
    type: string
    size?: 'xsmall' | 'small' | 'medium'
    sizePx?: number
    disableTooltip?: boolean
}): JSX.Element {
    const sizePx = sizePxProps ?? SIZE_PX_MAP[size]

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
        PostHog: IconPostHog,
    }[type]

    if (disableTooltip) {
        return (
            <div className="flex items-center gap-4">
                <img
                    src={icon}
                    alt={type}
                    height={sizePx}
                    width={sizePx}
                    className="rounded object-contain max-w-none"
                />
            </div>
        )
    }

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

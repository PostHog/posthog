import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import BlushingHog from '~/assets/hedgehog/blushing-hog.png'
import IconPostHog from '~/assets/posthog-icon.svg'
import IconAwsS3 from '~/assets/services/aws-s3.png'
import Iconazure from '~/assets/services/azure.png'
import IconBigQuery from '~/assets/services/bigquery.png'
import IconBraze from '~/assets/services/braze.png'
import IconChargebee from '~/assets/services/chargebee.png'
import IconCloudflare from '~/assets/services/cloudflare.png'
import IconDoIt from '~/assets/services/doit.svg'
import IconGoogleSheets from '~/assets/services/Google_Sheets.svg'
import IconGoogleAds from '~/assets/services/google-ads.png'
import IconGoogleCloudStorage from '~/assets/services/google-cloud-storage.png'
import IconHubspot from '~/assets/services/hubspot.png'
import IconKlaviyo from '~/assets/services/klaviyo.png'
import IconMailchimp from '~/assets/services/mailchimp.png'
import IconMailjet from '~/assets/services/mailjet.png'
import IconMetaAds from '~/assets/services/meta-ads.png'
import IconMongodb from '~/assets/services/Mongodb.svg'
import IconMySQL from '~/assets/services/mysql.png'
import IconPostgres from '~/assets/services/postgres.png'
import IconRedshift from '~/assets/services/redshift.png'
import IconSalesforce from '~/assets/services/salesforce.png'
import IconSnowflake from '~/assets/services/snowflake.png'
import IconMSSQL from '~/assets/services/sql-azure.png'
import IconStripe from '~/assets/services/stripe.png'
import IconTemporalIO from '~/assets/services/temporal.png'
import IconVitally from '~/assets/services/vitally.png'
import IconZendesk from '~/assets/services/zendesk.png'
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

export function mapUrlToSourceName(url: string): string {
    if (url.includes('amazonaws.com')) {
        return 'AWS'
    } else if (url.startsWith('https://storage.googleapis.com')) {
        return 'GCS'
    } else if (url.includes('.blob.')) {
        return 'Azure'
    } else if (url.includes('.r2.cloudflarestorage.com')) {
        return 'Cloudflare'
    }
    return 'BlushingHog'
}

const SIZE_PX_MAP = {
    xsmall: 16,
    small: 30,
    medium: 60,
}

export const DATA_WAREHOUSE_SOURCE_ICON_MAP: Record<string, string> = {
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
    GoogleAds: IconGoogleAds,
    MetaAds: IconMetaAds,
    Klaviyo: IconKlaviyo,
    Mailchimp: IconMailchimp,
    Braze: IconBraze,
    Mailjet: IconMailjet,
    Redshift: IconRedshift,
    GoogleSheets: IconGoogleSheets,
    MongoDB: IconMongodb,
    TemporalIO: IconTemporalIO,
    DoIt: IconDoIt,
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

    const icon = DATA_WAREHOUSE_SOURCE_ICON_MAP[type]

    if (disableTooltip) {
        return (
            <div className="flex gap-4 items-center">
                <img
                    src={icon}
                    alt={type}
                    height={sizePx}
                    width={sizePx}
                    className="object-contain max-w-none rounded"
                />
            </div>
        )
    }

    return (
        <div className="flex gap-4 items-center">
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
                        className="object-contain max-w-none rounded"
                    />
                </Link>
            </Tooltip>
        </div>
    )
}

import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import BlushingHog from 'public/hedgehog/blushing-hog.png'
import IconPostHog from 'public/posthog-icon.svg'
import IconAwsS3 from 'public/services/aws-s3.png'
import Iconazure from 'public/services/azure.png'
import IconBigQuery from 'public/services/bigquery.png'
import IconBraze from 'public/services/braze.png'
import IconChargebee from 'public/services/chargebee.png'
import IconCloudflare from 'public/services/cloudflare.png'
import IconDoIt from 'public/services/doit.svg'
import IconGoogleSheets from 'public/services/Google_Sheets.svg'
import IconGoogleAds from 'public/services/google-ads.png'
import IconGoogleCloudStorage from 'public/services/google-cloud-storage.png'
import IconHubspot from 'public/services/hubspot.png'
import IconKlaviyo from 'public/services/klaviyo.png'
import IconMailchimp from 'public/services/mailchimp.png'
import IconMailjet from 'public/services/mailjet.png'
import IconMetaAds from 'public/services/meta-ads.png'
import IconMongodb from 'public/services/Mongodb.svg'
import IconMySQL from 'public/services/mysql.png'
import IconPostgres from 'public/services/postgres.png'
import IconRedshift from 'public/services/redshift.png'
import IconSalesforce from 'public/services/salesforce.png'
import IconSnowflake from 'public/services/snowflake.png'
import IconMSSQL from 'public/services/sql-azure.png'
import IconStripe from 'public/services/stripe.png'
import IconTemporalIO from 'public/services/temporal.png'
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
        GoogleAds: IconGoogleAds,
        MetaAds: IconMetaAds,
        Klaviyo: IconKlaviyo,
        Mailchimp: IconMailchimp,
        Braze: IconBraze,
        Mailjet: IconMailjet,
        Redshift: IconRedshift,
        GoogleSheets: IconGoogleSheets,
        Mongodb: IconMongodb,
        TemporalIO: IconTemporalIO,
        DoIt: IconDoIt,
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

import { capitalizeFirstLetter } from 'lib/utils/strings'

import { IntegrationKind } from '~/types'

import IconAwsS3 from 'public/services/aws-s3.png'
import IconAzureBlob from 'public/services/azure-blob-storage.png'
import IconBingAds from 'public/services/bing-ads.svg'
import IconClickUp from 'public/services/clickup.svg'
import IconCustomerIO from 'public/services/customer-io.png'
import IconDatabricks from 'public/services/databricks.png'
import IconFirebase from 'public/services/firebase.png'
import IconGitHub from 'public/services/github.png'
import IconGitLab from 'public/services/gitlab.png'
import IconGoogleAds from 'public/services/google-ads.png'
import IconGoogleCloudStorage from 'public/services/google-cloud-storage.png'
import IconGoogleCloud from 'public/services/google-cloud.png'
import IconGoogleSearchConsole from 'public/services/google-search-console.svg'
import IconGoogleSheets from 'public/services/google-sheets.svg'
import IconGoogleAnalytics from 'public/services/google_analytics.png'
import IconHubspot from 'public/services/hubspot.png'
import IconIntercom from 'public/services/intercom.png'
import IconJira from 'public/services/jira.svg'
import IconLinear from 'public/services/linear.png'
import IconLinkedIn from 'public/services/linkedin.png'
import IconMailjet from 'public/services/mailjet.png'
import IconMetaAds from 'public/services/meta-ads.png'
import IconPinterest from 'public/services/pinterest_ads.png'
import IconPostgres from 'public/services/postgres.png'
import IconReddit from 'public/services/reddit.png'
import IconS3Compatible from 'public/services/s3-compatible.png'
import IconSalesforce from 'public/services/salesforce.png'
import IconSlack from 'public/services/slack.png'
import IconSnapchat from 'public/services/snapchat.png'
import IconStripe from 'public/services/stripe.png'
import IconTikTok from 'public/services/tiktok.png'
import IconTwilio from 'public/services/twilio.png'
import IconVercel from 'public/services/vercel.png'

export const ICONS: Record<IntegrationKind, any> = {
    slack: IconSlack,
    salesforce: IconSalesforce,
    hubspot: IconHubspot,
    'google-pubsub': IconGoogleCloud,
    'google-cloud-storage': IconGoogleCloudStorage,
    'google-cloud-service-account': IconGoogleCloud,
    'google-ads': IconGoogleAds,
    'google-analytics': IconGoogleAnalytics,
    'google-search-console': IconGoogleSearchConsole,
    'google-sheets': IconGoogleSheets,
    snapchat: IconSnapchat,
    stripe: IconStripe,
    intercom: IconIntercom,
    'linkedin-ads': IconLinkedIn,
    email: IconMailjet,
    linear: IconLinear,
    github: IconGitHub,
    gitlab: IconGitLab,
    'meta-ads': IconMetaAds,
    twilio: IconTwilio,
    clickup: IconClickUp,
    'reddit-ads': IconReddit,
    databricks: IconDatabricks,
    'tiktok-ads': IconTikTok,
    'bing-ads': IconBingAds,
    vercel: IconVercel,
    'azure-blob': IconAzureBlob,
    firebase: IconFirebase,
    jira: IconJira,
    'pinterest-ads': IconPinterest,
    'customerio-app': IconCustomerIO,
    'customerio-webhook': IconCustomerIO,
    'customerio-track': IconCustomerIO,
    postgresql: IconPostgres,
    'aws-s3': IconAwsS3,
    's3-compatible': IconS3Compatible,
}

export const getIntegrationNameFromKind = (kind: string): string => {
    switch (kind) {
        case 'google-pubsub':
            return 'Google Cloud Pub/Sub'
        case 'google-cloud-storage':
            return 'Google Cloud Storage'
        case 'google-ads':
            return 'Google Ads'
        case 'google-analytics':
            return 'Google Analytics'
        case 'google-search-console':
            return 'Google Search Console'
        case 'google-cloud-service-account':
            return 'Google Cloud service account'
        case 'linkedin-ads':
            return 'LinkedIn Ads'
        case 'reddit-ads':
            return 'Reddit Ads'
        case 'tiktok-ads':
            return 'TikTok Ads'
        case 'bing-ads':
            return 'Bing Ads'
        case 'azure-blob':
            return 'Azure Blob Storage'
        case 'pinterest-ads':
            return 'Pinterest Ads'
        case 'email':
            return 'email'
        case 'github':
            return 'GitHub'
        case 'firebase':
            return 'Firebase'
        case 'postgresql':
            return 'PostgreSQL'
        case 'aws-s3':
            return 'AWS S3'
        case 's3-compatible':
            return 'S3-compatible storage'
        default:
            return capitalizeFirstLetter(kind)
    }
}

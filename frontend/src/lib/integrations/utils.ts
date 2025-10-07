import { capitalizeFirstLetter } from 'lib/utils'

import { IntegrationKind } from '~/types'

import IconClickUp from 'public/services/clickup.svg'
import IconDatabricks from 'public/services/databricks.png'
import IconGitHub from 'public/services/github.png'
import IconGoogleAds from 'public/services/google-ads.png'
import IconGoogleCloudStorage from 'public/services/google-cloud-storage.png'
import IconGoogleCloud from 'public/services/google-cloud.png'
import IconGoogleSheets from 'public/services/google-sheets.svg'
import IconHubspot from 'public/services/hubspot.png'
import IconIntercom from 'public/services/intercom.png'
import IconLinear from 'public/services/linear.png'
import IconLinkedIn from 'public/services/linkedin.png'
import IconMailjet from 'public/services/mailjet.png'
import IconMetaAds from 'public/services/meta-ads.png'
import IconReddit from 'public/services/reddit.png'
import IconSalesforce from 'public/services/salesforce.png'
import IconSlack from 'public/services/slack.png'
import IconSnapchat from 'public/services/snapchat.png'
import IconTwilio from 'public/services/twilio.png'

export const ICONS: Record<IntegrationKind, any> = {
    slack: IconSlack,
    salesforce: IconSalesforce,
    hubspot: IconHubspot,
    'google-pubsub': IconGoogleCloud,
    'google-cloud-storage': IconGoogleCloudStorage,
    'google-ads': IconGoogleAds,
    'google-sheets': IconGoogleSheets,
    snapchat: IconSnapchat,
    intercom: IconIntercom,
    'linkedin-ads': IconLinkedIn,
    email: IconMailjet,
    linear: IconLinear,
    github: IconGitHub,
    'meta-ads': IconMetaAds,
    twilio: IconTwilio,
    clickup: IconClickUp,
    'reddit-ads': IconReddit,
    databricks: IconDatabricks,
}

export const getIntegrationNameFromKind = (kind: string): string => {
    switch (kind) {
        case 'google-pubsub':
            return 'Google Cloud Pub/Sub'
        case 'google-cloud-storage':
            return 'Google Cloud Storage'
        case 'google-ads':
            return 'Google Ads'
        case 'linkedin-ads':
            return 'LinkedIn Ads'
        case 'reddit-ads':
            return 'Reddit Ads'
        case 'email':
            return 'email'
        case 'github':
            return 'GitHub'
        default:
            return capitalizeFirstLetter(kind)
    }
}

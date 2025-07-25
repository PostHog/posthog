import IconGoogleAds from 'public/services/google-ads.png'
import IconGoogleCloud from 'public/services/google-cloud.png'
import IconGoogleCloudStorage from 'public/services/google-cloud-storage.png'
import IconHubspot from 'public/services/hubspot.png'
import IconIntercom from 'public/services/intercom.png'
import IconLinear from 'public/services/linear.png'
import IconGitHub from 'public/services/github.png'
import IconLinkedIn from 'public/services/linkedin.png'
import IconMailjet from 'public/services/mailjet.png'
import IconSalesforce from 'public/services/salesforce.png'
import IconSlack from 'public/services/slack.png'
import IconSnapchat from 'public/services/snapchat.png'
import IconMetaAds from 'public/services/meta-ads.png'
import IconTwilio from 'public/services/twilio.png'

import { capitalizeFirstLetter } from 'lib/utils'
import { IntegrationKind } from '~/types'

export const ICONS: Record<IntegrationKind, any> = {
    slack: IconSlack,
    salesforce: IconSalesforce,
    hubspot: IconHubspot,
    'google-pubsub': IconGoogleCloud,
    'google-cloud-storage': IconGoogleCloudStorage,
    'google-ads': IconGoogleAds,
    snapchat: IconSnapchat,
    intercom: IconIntercom,
    'linkedin-ads': IconLinkedIn,
    email: IconMailjet,
    linear: IconLinear,
    github: IconGitHub,
    'meta-ads': IconMetaAds,
    twilio: IconTwilio,
}

export const getIntegrationNameFromKind = (kind: string): string => {
    return kind == 'google-pubsub'
        ? 'Google Cloud Pub/Sub'
        : kind == 'google-cloud-storage'
        ? 'Google Cloud Storage'
        : kind == 'google-ads'
        ? 'Google Ads'
        : kind == 'linkedin-ads'
        ? 'LinkedIn Ads'
        : kind == 'email'
        ? 'email'
        : kind == 'github'
        ? 'GitHub'
        : capitalizeFirstLetter(kind)
}

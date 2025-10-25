import { DESTINATION_PLUGINS, TRANSFORMATION_PLUGINS } from '../legacy-plugins'
import { SEGMENT_DESTINATIONS } from '../segment/segment-templates'
import { HogFunctionTemplate, NativeTemplate } from '../types'
import { template as accoilTemplate } from './_destinations/accoil/accoil.template'
import { template as clickupTemplate } from './_destinations/clickup/clickup.template'
import { allComingSoonTemplates } from './_destinations/coming-soon/coming-soon-destinations.template'
import { template as emailTemplate } from './_destinations/email/email.template'
import { template as githubTemplate } from './_destinations/github/github.template'
import { template as gitlabTemplate } from './_destinations/gitlab/gitlab.template'
import { template as googleTagManagerTemplate } from './_destinations/google-tag-manager/google-tag-manager.template'
import { template as googleAdsTemplate } from './_destinations/google_ads/google.template'
import { template as googleSheetsTemplate } from './_destinations/google_sheets/google_sheets.template'
import { template as hubspotCompanyTemplate } from './_destinations/hubspot/hubspot.template'
import { template as linearTemplate } from './_destinations/linear/linear.template'
import { template as linkedinAdsTemplate } from './_destinations/linkedin_ads/linkedin.template'
import { template as nativeWebhookTemplate } from './_destinations/native_webhook/webhook.template'
import { template as posthogCaptureTemplate } from './_destinations/posthog_capture/posthog-capture.template'
import { template as posthogGroupIdentifyTemplate } from './_destinations/posthog_capture/posthog-group-identify.template'
import { template as posthogUpdatePersonPropertiesTemplate } from './_destinations/posthog_capture/posthog-update-person-properties.template'
import { template as redditAdsTemplate } from './_destinations/reddit_ads/reddit.template'
import { template as snapchatAdsTemplate } from './_destinations/snapchat_ads/snapchat.template'
import { template as tiktokAdsTemplate } from './_destinations/tiktok_ads/tiktok.template'
import { template as twilioTemplate } from './_destinations/twilio/twilio.template'
import { template as webhookTemplate } from './_destinations/webhook/webhook.template'
import { template as pixelTemplate } from './_sources/pixel/pixel.template'
import { template as stripeWebhookTemplate } from './_sources/stripe/stripe_webhook.template'
import { template as incomingWebhookTemplate } from './_sources/webhook/incoming_webhook.template'
import { template as botDetectionTemplate } from './_transformations/bot-detection/bot-detection.template'
import { template as defaultTransformationTemplate } from './_transformations/default/default.template'
import { template as dropEventsTemplate } from './_transformations/drop-events/drop-events.template'
import { template as filterPropertiesTemplate } from './_transformations/filter-properties/filter-properties.template'
import { template as geoipTemplate } from './_transformations/geoip/geoip.template'
import { template as hashPropertiesTemplate } from './_transformations/hash-properties/hash-properties.template'
import { template as ipAnonymizationTemplate } from './_transformations/ip-anonymization/ip-anonymization.template'
import { template as piiHashingTemplate } from './_transformations/pii-hashing/pii-hashing.template'
import { template as removeNullPropertiesTemplate } from './_transformations/remove-null-properties/remove-null-properties.template'
import { template as urlMaskingTemplate } from './_transformations/url-masking/url-masking.template'
import { template as urlNormalizationTemplate } from './_transformations/url-normalization/url-normalization.template'

export const HOG_FUNCTION_TEMPLATES_COMING_SOON: HogFunctionTemplate[] = allComingSoonTemplates

export const HOG_FUNCTION_TEMPLATES_DESTINATIONS: HogFunctionTemplate[] = [
    webhookTemplate,
    tiktokAdsTemplate,
    snapchatAdsTemplate,
    linearTemplate,
    githubTemplate,
    gitlabTemplate,
    googleAdsTemplate,
    linkedinAdsTemplate,
    redditAdsTemplate,
    twilioTemplate,
    googleSheetsTemplate,
    googleTagManagerTemplate,
    emailTemplate,
    clickupTemplate,
    posthogCaptureTemplate,
    posthogGroupIdentifyTemplate,
    posthogUpdatePersonPropertiesTemplate,
    hubspotCompanyTemplate,
    accoilTemplate,
]

export const HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS: HogFunctionTemplate[] = [
    defaultTransformationTemplate,
    geoipTemplate,
    ipAnonymizationTemplate,
    removeNullPropertiesTemplate,
    urlMaskingTemplate,
    piiHashingTemplate,
    botDetectionTemplate,
    dropEventsTemplate,
    filterPropertiesTemplate,
    hashPropertiesTemplate,
    urlNormalizationTemplate,
]

export const NATIVE_HOG_FUNCTIONS: (HogFunctionTemplate & NativeTemplate)[] = [nativeWebhookTemplate].map((plugin) => ({
    ...plugin,
    code_language: 'javascript',
    code: 'return event;',
    inputs_schema: [
        ...plugin.inputs_schema,
        {
            key: 'debug_mode',
            label: 'Debug Mode',
            type: 'boolean',
            description: 'Will log configuration and request details',
            default: false,
        },
    ],
}))

export const HOG_FUNCTION_TEMPLATES_SOURCES: HogFunctionTemplate[] = [
    incomingWebhookTemplate,
    stripeWebhookTemplate,
    pixelTemplate,
]

export const HOG_FUNCTION_TEMPLATES_DESTINATIONS_DEPRECATED: HogFunctionTemplate[] = DESTINATION_PLUGINS.map(
    (x) => x.template
)

export const HOG_FUNCTION_TEMPLATES_SEGMENT_DESTINATIONS: HogFunctionTemplate[] = SEGMENT_DESTINATIONS.map(
    (x) => x.template
)

export const HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS_DEPRECATED: HogFunctionTemplate[] = TRANSFORMATION_PLUGINS.map(
    (x) => x.template
)

export const NATIVE_HOG_FUNCTIONS_BY_ID = NATIVE_HOG_FUNCTIONS.reduce(
    (acc, plugin) => {
        acc[plugin.id] = plugin
        return acc
    },
    {} as Record<string, NativeTemplate>
)

export const HOG_FUNCTION_TEMPLATES: HogFunctionTemplate[] = [
    ...HOG_FUNCTION_TEMPLATES_DESTINATIONS,
    ...HOG_FUNCTION_TEMPLATES_SEGMENT_DESTINATIONS,
    ...HOG_FUNCTION_TEMPLATES_DESTINATIONS_DEPRECATED,
    ...HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS,
    ...HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS_DEPRECATED,
    ...HOG_FUNCTION_TEMPLATES_SOURCES,
    ...HOG_FUNCTION_TEMPLATES_COMING_SOON,
    ...NATIVE_HOG_FUNCTIONS,
]

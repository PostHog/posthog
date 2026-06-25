import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'template-native-push',
    name: 'Push notification',
    description: 'Send push notifications to mobile devices via FCM or APNS',
    icon_url: '/static/posthog-icon.svg',
    category: ['Communication'],
    code_language: 'hog',
    code: `
let payload := {
    'title': inputs.title,
    'body': inputs.body
}

if (inputs.image) payload.image := inputs.image
if (inputs.data) payload.data := inputs.data
if (inputs.collapseKey) payload.collapseKey := inputs.collapseKey
if (inputs.ttlSeconds) payload.ttlSeconds := inputs.ttlSeconds

// Android-specific overrides from mapping
let android := {}
if (inputs.android_priority) android.priority := inputs.android_priority
if (inputs.android_channelId) android.channelId := inputs.android_channelId
if (inputs.android_sound) android.sound := inputs.android_sound
if (inputs.android_tag) android.tag := inputs.android_tag
if (inputs.android_icon) android.icon := inputs.android_icon
if (inputs.android_color) android.color := inputs.android_color
if (inputs.android_clickAction) android.clickAction := inputs.android_clickAction
if (length(keys(android)) > 0) payload.android := android

// iOS (APNS) overrides from mapping
let apns := {}
if (inputs.ios_sound) apns.sound := inputs.ios_sound
if (inputs.ios_badge != null) apns.badge := inputs.ios_badge
if (inputs.ios_category) apns.category := inputs.ios_category
if (inputs.ios_threadId) apns.threadId := inputs.ios_threadId
if (inputs.ios_interruptionLevel) apns.interruptionLevel := inputs.ios_interruptionLevel
if (inputs.ios_subtitle) apns.subtitle := inputs.ios_subtitle
if (inputs.ios_mutableContent) apns.mutableContent := inputs.ios_mutableContent
if (length(keys(apns)) > 0) payload.apns := apns

if (not inputs.push_provider) {
    throw Error('Push provider integration not configured')
}

let res := sendPushNotification({
    'integrationId': inputs.push_provider.$integration_id,
    'distinctId': inputs.distinctId,
    'payload': payload
})

if (not res.success) {
    throw Error(f'Failed to send push notification: {res.error}')
}
`,
    inputs_schema: [
        {
            key: 'distinctId',
            type: 'string',
            label: 'Distinct ID',
            secret: false,
            required: true,
            description: 'Distinct ID of the person to send the notification to.',
            default: '{event.distinct_id}',
        },
        {
            key: 'title',
            type: 'string',
            label: 'Notification title',
            secret: false,
            required: true,
            description: 'The title of the push notification.',
            default: 'Notification from {event.event}',
        },
        {
            key: 'body',
            type: 'string',
            label: 'Notification body',
            secret: false,
            required: false,
            description: 'The body text of the push notification.',
            default: '',
            templating: 'liquid',
        },
        {
            key: 'image',
            type: 'string',
            label: 'Image URL',
            secret: false,
            required: false,
            description: 'URL of an image to display in the notification.',
        },
        {
            key: 'data',
            type: 'json',
            label: 'Custom data payload',
            secret: false,
            required: false,
            description: 'Custom key-value data delivered to the app (values must be strings for FCM).',
            default: {},
        },
        {
            key: 'collapseKey',
            type: 'string',
            label: 'Collapse key',
            secret: false,
            required: false,
            description:
                'Identifier for grouping notifications. Only the latest notification with a given key is shown.',
        },
        {
            key: 'ttlSeconds',
            type: 'number',
            label: 'TTL (seconds)',
            secret: false,
            required: false,
            description: 'Time-to-live in seconds. How long FCM stores the message if the device is offline.',
        },
    ],
    mapping_templates: [
        {
            name: 'FCM configuration',
            include_by_default: true,
            use_all_events_by_default: true,
            inputs_schema: [
                {
                    key: 'push_provider',
                    type: 'integration',
                    integration: 'firebase',
                    label: 'Firebase project',
                    requiredScopes: 'placeholder',
                    secret: false,
                    required: true,
                },
                // Android-specific options
                {
                    key: 'android_priority',
                    type: 'choice',
                    label: 'Android priority',
                    choices: [
                        { value: 'normal', label: 'Normal' },
                        { value: 'high', label: 'High' },
                    ],
                    description: 'Message delivery priority. High priority wakes the device immediately.',
                    required: false,
                },
                {
                    key: 'android_channelId',
                    type: 'string',
                    label: 'Android channel ID',
                    description: 'Android notification channel ID (Android 8.0+).',
                    required: false,
                },
                {
                    key: 'android_sound',
                    type: 'string',
                    label: 'Android sound',
                    description: 'Sound to play on Android. Use "default" for the system default.',
                    required: false,
                },
                {
                    key: 'android_tag',
                    type: 'string',
                    label: 'Android tag',
                    description: 'Notification tag. Replaces an existing notification with the same tag.',
                    required: false,
                },
                {
                    key: 'android_icon',
                    type: 'string',
                    label: 'Android icon',
                    description: 'Notification icon resource name.',
                    required: false,
                },
                {
                    key: 'android_color',
                    type: 'string',
                    label: 'Android color',
                    description: 'Notification icon color in #RRGGBB format.',
                    required: false,
                },
                {
                    key: 'android_clickAction',
                    type: 'string',
                    label: 'Android click action',
                    description: 'Activity to launch when the notification is tapped.',
                    required: false,
                },
                // iOS (APNS) overrides — FCM delivers to iOS devices with these settings
                {
                    key: 'ios_sound',
                    type: 'string',
                    label: 'iOS sound',
                    description: 'Sound file name or "default" for the system default.',
                    required: false,
                },
                {
                    key: 'ios_badge',
                    type: 'number',
                    label: 'iOS badge count',
                    description: 'App icon badge number.',
                    required: false,
                },
                {
                    key: 'ios_subtitle',
                    type: 'string',
                    label: 'iOS subtitle',
                    description: 'Additional text below the title.',
                    required: false,
                },
                {
                    key: 'ios_category',
                    type: 'string',
                    label: 'iOS category',
                    description: 'Notification category for actionable notifications.',
                    required: false,
                },
                {
                    key: 'ios_threadId',
                    type: 'string',
                    label: 'iOS thread ID',
                    description: 'Identifier for grouping notifications in the notification center.',
                    required: false,
                },
                {
                    key: 'ios_interruptionLevel',
                    type: 'choice',
                    label: 'iOS interruption level',
                    choices: [
                        { value: 'passive', label: 'Passive' },
                        { value: 'active', label: 'Active' },
                        { value: 'time-sensitive', label: 'Time sensitive' },
                        { value: 'critical', label: 'Critical' },
                    ],
                    description: 'How prominently the notification is presented (iOS 15+).',
                    required: false,
                },
                {
                    key: 'ios_mutableContent',
                    type: 'boolean',
                    label: 'iOS mutable content',
                    description: 'Allow a notification service extension to modify the content before display.',
                    required: false,
                    default: false,
                },
            ],
        },
        {
            name: 'APNS (iOS) configuration',
            include_by_default: true,
            use_all_events_by_default: true,
            inputs_schema: [
                {
                    key: 'push_provider',
                    type: 'integration',
                    integration: 'apns',
                    label: 'Apple Push provider',
                    requiredScopes: 'placeholder',
                    secret: false,
                    required: true,
                },
                {
                    key: 'ios_sound',
                    type: 'string',
                    label: 'Sound',
                    description: 'Sound file name or "default" for the system default.',
                    required: false,
                },
                {
                    key: 'ios_badge',
                    type: 'number',
                    label: 'Badge count',
                    description: 'App icon badge number.',
                    required: false,
                },
                {
                    key: 'ios_subtitle',
                    type: 'string',
                    label: 'Subtitle',
                    description: 'Additional text below the title.',
                    required: false,
                },
                {
                    key: 'ios_category',
                    type: 'string',
                    label: 'Category',
                    description: 'Notification category for actionable notifications.',
                    required: false,
                },
                {
                    key: 'ios_threadId',
                    type: 'string',
                    label: 'Thread ID',
                    description: 'Identifier for grouping notifications in the notification center.',
                    required: false,
                },
                {
                    key: 'ios_interruptionLevel',
                    type: 'choice',
                    label: 'Interruption level',
                    choices: [
                        { value: 'passive', label: 'Passive' },
                        { value: 'active', label: 'Active' },
                        { value: 'time-sensitive', label: 'Time sensitive' },
                        { value: 'critical', label: 'Critical' },
                    ],
                    description: 'How prominently the notification is presented (iOS 15+).',
                    required: false,
                },
                {
                    key: 'ios_mutableContent',
                    type: 'boolean',
                    label: 'Mutable content',
                    description: 'Allow a notification service extension to modify the content before display.',
                    required: false,
                    default: false,
                },
            ],
        },
    ],
}

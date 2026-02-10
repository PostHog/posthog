import { HogFunctionTemplate } from '~/cdp/types'

// push_subscription input gets resolved to FCM token in hog-inputs.service.ts
export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'template-firebase-push',
    name: 'Firebase Push Notification',
    description: 'Send push notifications to mobile devices via Firebase Cloud Messaging (FCM)',
    icon_url: '/static/services/firebase.png',
    category: ['Communication'],
    code_language: 'hog',
    code: `
let fcmToken := inputs.push_subscription

if (not fcmToken) {
    print(f'No push subscription found for the targeted person. Skipping push notification for event: {event.uuid}')
    return
}

let title := inputs.title
let body := inputs.body
let projectId := inputs.firebase_account.project_id

if (not title) {
    throw Error('Notification title is required')
}

let url := f'https://fcm.googleapis.com/v1/projects/{projectId}/messages:send'

let message := {
    'message': {
        'token': fcmToken,
        'notification': {
            'title': title,
            'body': body
        }
    }
}

if (inputs.data) {
    message.message.data := inputs.data
}

let payload := {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.firebase_account.access_token}',
        'Content-Type': 'application/json'
    },
    'body': message,
    'timeoutMs': 10000
}

if (inputs.debug) {
    print('Sending push notification', url, payload)
}

let res := sendPushNotification(url, payload)

if (res.status < 200 or res.status >= 300) {
    throw Error(f'Failed to send push notification via FCM: {res.status} {res.body}')
}

if (inputs.debug) {
    print('Push notification sent', res)
}
`,
    inputs_schema: [
        {
            key: 'firebase_account',
            type: 'integration',
            integration: 'firebase',
            label: 'Firebase project',
            requiredScopes: 'placeholder',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'push_subscription',
            type: 'push_subscription',
            label: 'Distinct ID',
            secret: false,
            required: true,
            description:
                'Distinct ID of the person to send to (used to look up the device FCM token). Use {{ event.distinct_id }} for the person associated with the event.',
            platform: 'android',
            default: '{{ event.distinct_id }}',
            templating: 'liquid',
        },
        {
            key: 'title',
            type: 'string',
            label: 'Notification title',
            secret: false,
            required: true,
            description: 'The title of the push notification',
            default: 'Notification from {{ event.event }}',
            templating: 'liquid',
        },
        {
            key: 'body',
            type: 'string',
            label: 'Notification body',
            secret: false,
            required: false,
            description: 'The body text of the push notification',
            default: '',
            templating: 'liquid',
        },
        {
            key: 'data',
            type: 'json',
            label: 'Custom data payload',
            secret: false,
            required: false,
            description: 'Optional custom key-value data to send with the notification (for app handling)',
            default: {},
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the FCM responses for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
}

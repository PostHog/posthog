import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-firebase-push',
    name: 'Firebase Push Notification',
    description: 'Send push notifications to mobile devices via Firebase Cloud Messaging (FCM)',
    icon_url: '/static/services/firebase.png',
    category: ['Communication'],
    code_language: 'hog',
    code: `
let fcmToken := inputs.fcm_token
let title := inputs.title
let body := inputs.body
let projectId := inputs.firebase_account.project_id

if (not fcmToken) {
    throw Error('FCM token is required')
}

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
    'body': message
}

if (inputs.debug) {
    print('Sending push notification', url, payload)
}

let res := fetch(url, payload)

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
            key: 'fcm_token',
            type: 'string',
            label: 'FCM device token',
            secret: false,
            required: true,
            description:
                'The Firebase Cloud Messaging token for the target device. In a future version, this will be automatically looked up from registered devices.',
            default: '',
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

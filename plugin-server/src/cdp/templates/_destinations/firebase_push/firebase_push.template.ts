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
let title := inputs.title
let body := inputs.body
let projectId := inputs.firebase_account.project_id

if (not title) {
    throw Error('Notification title is required')
}

// Get FCM tokens - either from input or lookup by distinct_id
let tokens := []

if (inputs.fcm_token) {
    // Manual token provided
    tokens := [inputs.fcm_token]
} else if (inputs.lookup_tokens) {
    // Lookup tokens from PushSubscription model
    let lookupUrl := f'{project.url}/api/internal/push_subscriptions/lookup/'
    let lookupPayload := {
        'method': 'POST',
        'headers': {
            'Content-Type': 'application/json'
        },
        'body': {
            'team_id': project.id,
            'distinct_id': event.distinct_id
        }
    }

    if (inputs.debug) {
        print('Looking up push tokens', lookupUrl, lookupPayload)
    }

    let lookupRes := fetch(lookupUrl, lookupPayload)

    if (lookupRes.status >= 200 and lookupRes.status < 300) {
        let lookupData := lookupRes.body
        if (lookupData.tokens) {
            for (let t in lookupData.tokens) {
                tokens := arrayPushBack(tokens, t.token)
            }
        }
    } else if (inputs.debug) {
        print('Token lookup failed', lookupRes.status, lookupRes.body)
    }
}

if (empty(tokens)) {
    if (inputs.debug) {
        print('No FCM tokens found for user', event.distinct_id)
    }
    return
}

let fcmUrl := f'https://fcm.googleapis.com/v1/projects/{projectId}/messages:send'
let successCount := 0
let failCount := 0

for (let fcmToken in tokens) {
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
        print('Sending push notification', fcmUrl, payload)
    }

    let res := fetch(fcmUrl, payload)

    if (res.status >= 200 and res.status < 300) {
        successCount := successCount + 1
        if (inputs.debug) {
            print('Push notification sent', res)
        }
    } else {
        failCount := failCount + 1
        if (inputs.debug) {
            print('Push notification failed', res.status, res.body)
        }
    }
}

if (inputs.debug) {
    print(f'Push notifications complete: {successCount} sent, {failCount} failed')
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
            key: 'lookup_tokens',
            type: 'boolean',
            label: 'Automatically lookup device tokens',
            secret: false,
            required: false,
            description:
                'When enabled, automatically looks up FCM tokens registered by mobile SDKs for the user who triggered the event. Requires the mobile app to call PostHog.setFcmToken().',
            default: true,
        },
        {
            key: 'fcm_token',
            type: 'string',
            label: 'FCM device token (manual)',
            secret: false,
            required: false,
            description:
                'Manually specify an FCM token. Only used if "Automatically lookup device tokens" is disabled.',
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

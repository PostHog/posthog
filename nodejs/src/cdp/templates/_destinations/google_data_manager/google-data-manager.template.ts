import { HogFunctionInputSchemaType, HogFunctionTemplate } from '~/cdp/types'

const buildInputs = (): HogFunctionInputSchemaType[] => [
    {
        key: 'conversionActionId',
        type: 'integration_field',
        integration_key: 'oauth',
        integration_field: 'google_ads_conversion_action',
        requires_field: 'customerId',
        label: 'Conversion action',
        description: 'The Google Ads conversion action that receives this event.',
        secret: false,
        required: true,
    },
    {
        key: 'gclid',
        type: 'string',
        label: 'Google Click ID (gclid)',
        description: 'The Google click ID associated with this conversion.',
        default: '{person.properties.gclid ?? person.properties.$initial_gclid}',
        secret: false,
        required: false,
    },
    {
        key: 'gbraid',
        type: 'string',
        label: 'Google braid ID (gbraid)',
        description: 'The Google app-click identifier associated with this conversion.',
        default: '{person.properties.gbraid ?? person.properties.$initial_gbraid}',
        secret: false,
        required: false,
    },
    {
        key: 'wbraid',
        type: 'string',
        label: 'Google braid ID (wbraid)',
        description: 'The Google web-click identifier associated with this conversion.',
        default: '{person.properties.wbraid ?? person.properties.$initial_wbraid}',
        secret: false,
        required: false,
    },
    {
        key: 'eventTimestamp',
        type: 'string',
        label: 'Event timestamp',
        description: 'The time the conversion occurred in RFC 3339 format.',
        default: '{event.timestamp}',
        secret: false,
        required: true,
    },
    {
        key: 'eventSource',
        type: 'choice',
        label: 'Event source',
        choices: [
            { label: 'Web', value: 'WEB' },
            { label: 'App', value: 'APP' },
            { label: 'In store', value: 'IN_STORE' },
            { label: 'Phone', value: 'PHONE' },
            { label: 'Message', value: 'MESSAGE' },
            { label: 'Other', value: 'OTHER' },
        ],
        default: 'WEB',
        secret: false,
        required: true,
    },
    {
        key: 'conversionValue',
        type: 'string',
        label: 'Conversion value',
        description: 'The value of this conversion.',
        default: '',
        secret: false,
        required: false,
    },
    {
        key: 'currency',
        type: 'string',
        label: 'Currency',
        description: 'The ISO 4217 currency code for the conversion value.',
        default: '',
        secret: false,
        required: false,
    },
    {
        key: 'transactionId',
        type: 'string',
        label: 'Transaction ID',
        description: 'A unique conversion identifier used to deduplicate events.',
        default: '',
        secret: false,
        required: false,
    },
    {
        key: 'email',
        type: 'string',
        label: 'Email address',
        description: 'Sent SHA-256 hashed. Normalize by lowercasing and trimming before sending.',
        default: '{person.properties.email}',
        secret: false,
        required: false,
    },
    {
        key: 'phone',
        type: 'string',
        label: 'Phone number',
        description: 'Sent SHA-256 hashed. Provide an E.164 phone number, for example +14255551234.',
        default: '',
        secret: false,
        required: false,
    },
    {
        key: 'adUserDataConsent',
        type: 'choice',
        label: 'Ad user data consent',
        choices: [
            { label: 'Unspecified', value: '' },
            { label: 'Granted', value: 'CONSENT_GRANTED' },
            { label: 'Denied', value: 'CONSENT_DENIED' },
        ],
        default: '',
        secret: false,
        required: false,
    },
    {
        key: 'adPersonalizationConsent',
        type: 'choice',
        label: 'Ad personalization consent',
        choices: [
            { label: 'Unspecified', value: '' },
            { label: 'Granted', value: 'CONSENT_GRANTED' },
            { label: 'Denied', value: 'CONSENT_DENIED' },
        ],
        default: '',
        secret: false,
        required: false,
    },
]

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-google-data-manager',
    name: 'Google Ads Data Manager',
    description: 'Send server-side conversion events to Google Ads using the Data Manager API',
    icon_url: '/static/services/google-ads.png',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
let userIdentifiers := []
if (not empty(inputs.email)) {
    userIdentifiers := arrayPushBack(userIdentifiers, {'email_address': sha256Hex(lower(trim(inputs.email)))})
}
if (not empty(inputs.phone)) {
    userIdentifiers := arrayPushBack(userIdentifiers, {'phone_number': sha256Hex(trim(inputs.phone))})
}

if (empty(inputs.gclid) and empty(inputs.gbraid) and empty(inputs.wbraid) and empty(userIdentifiers)) {
    print('No click ID or user identifiers. Skipping...')
    return
}

let event := {
    'eventTimestamp': inputs.eventTimestamp,
    'eventSource': inputs.eventSource
}
let adIdentifiers := {}
if (not empty(inputs.gclid)) {
    adIdentifiers.gclid := inputs.gclid
}
if (not empty(inputs.gbraid)) {
    adIdentifiers.gbraid := inputs.gbraid
}
if (not empty(inputs.wbraid)) {
    adIdentifiers.wbraid := inputs.wbraid
}
if (not empty(adIdentifiers)) {
    event.adIdentifiers := adIdentifiers
}
if (not empty(userIdentifiers)) {
    event.userData := {'userIdentifiers': userIdentifiers}
}
if (not empty(inputs.conversionValue)) {
    event.conversionValue := toFloat(inputs.conversionValue)
}
if (not empty(inputs.currency)) {
    event.currency := inputs.currency
}
if (not empty(inputs.transactionId)) {
    event.transactionId := inputs.transactionId
}

let consent := {}
if (not empty(inputs.adUserDataConsent)) {
    consent.adUserData := inputs.adUserDataConsent
}
if (not empty(inputs.adPersonalizationConsent)) {
    consent.adPersonalization := inputs.adPersonalizationConsent
}
if (not empty(consent)) {
    event.consent := consent
}

let accountIds := splitByString('/', inputs.customerId)
let destination := {
    'operatingAccount': {'accountType': 'GOOGLE_ADS', 'accountId': accountIds[1]},
    'productDestinationId': inputs.conversionActionId
}
if (not empty(accountIds[2])) {
    destination.loginAccount := {'accountType': 'GOOGLE_ADS', 'accountId': accountIds[2]}
}

let res := fetch('https://datamanager.googleapis.com/v1/events:ingest', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.oauth.access_token}',
        'Content-Type': 'application/json'
    },
    'body': {
        'destinations': [destination],
        'events': [event],
        'encoding': 'HEX'
    }
})

if (res.status >= 400) {
    throw Error(f'Error from datamanager.googleapis.com (status {res.status}): {res.body}')
}
if (not empty(res.body.requestId)) {
    print(f'Data Manager request accepted: {res.body.requestId}')
}
`,
    inputs_schema: [
        {
            key: 'oauth',
            type: 'integration',
            integration: 'google-ads',
            label: 'Google Ads account',
            requiredScopes:
                'https://www.googleapis.com/auth/adwords https://www.googleapis.com/auth/datamanager https://www.googleapis.com/auth/userinfo.email',
            secret: false,
            required: true,
        },
        {
            key: 'customerId',
            type: 'integration_field',
            integration_key: 'oauth',
            integration_field: 'google_ads_customer_id',
            label: 'Customer ID',
            description: 'The Google Ads account and optional manager account that receive this conversion.',
            secret: false,
            required: true,
        },
    ],
    mapping_templates: [
        {
            name: 'Conversion',
            include_by_default: true,
            filters: { events: [] },
            inputs_schema: buildInputs(),
        },
    ],
}

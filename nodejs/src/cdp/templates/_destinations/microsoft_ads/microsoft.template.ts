import { HogFunctionInputSchemaType, HogFunctionTemplate } from '~/cdp/types'

// Based on https://learn.microsoft.com/en-us/advertising/guides/uet-conversion-api-integration?view=bingads-13
// Sends server-to-server conversion events to the Microsoft Advertising Conversions API (CAPI).

const build_inputs = (): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'eventName',
            type: 'string',
            label: 'Event name',
            description:
                'The event action used to match a custom conversion goal in Microsoft Advertising. Must match the event configured on your conversion goal.',
            secret: false,
            required: true,
        },
        {
            key: 'microsoftClickId',
            type: 'string',
            label: 'Microsoft Click ID (msclkid)',
            description:
                'The Microsoft click ID (msclkid) associated with this conversion. Required for click attribution.',
            default: '{person.properties.msclkid ?? person.properties.$initial_msclkid}',
            secret: false,
            required: true,
        },
        {
            key: 'eventTime',
            type: 'string',
            label: 'Event time',
            description:
                'The time the event occurred, as a UNIX timestamp in seconds (UTC). Must be within the last 7 days.',
            default: '{toInt(toUnixTimestamp(event.timestamp))}',
            secret: false,
            required: true,
        },
        {
            key: 'eventId',
            type: 'string',
            label: 'Event ID',
            description: 'A unique ID for the event, used for deduplication against UET tag events.',
            default: '{event.uuid}',
            secret: false,
            required: false,
        },
        {
            key: 'conversionValue',
            type: 'string',
            label: 'Conversion value',
            description: 'The revenue value of the conversion.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'currency',
            type: 'string',
            label: 'Currency code',
            description: 'Currency of the conversion value as an ISO 4217 3-character code. For example: USD, EUR.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Email address',
            description:
                'Email address for enhanced conversions. Sent SHA-256 hashed; leave blank to omit. Normalize (lowercase, trimmed) for best match rates.',
            default: '{person.properties.email}',
            secret: false,
            required: false,
        },
        {
            key: 'phone',
            type: 'string',
            label: 'Phone number',
            description:
                'Phone number for enhanced conversions. Sent SHA-256 hashed; leave blank to omit. Normalize to E.164 format (e.g. +14255551234) for best match rates.',
            default: '',
            secret: false,
            required: false,
        },
    ]
}

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-microsoft-ads',
    name: 'Microsoft Ads Conversions',
    description: 'Send conversion events to the Microsoft Advertising Conversions API (CAPI)',
    icon_url: '/static/services/bing-ads.svg',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
if (empty(inputs.microsoftClickId)) {
    print('Empty \`microsoftClickId\`. Skipping...')
    return
}

let userData := {
    'msclkid': inputs.microsoftClickId
}
if (not empty(inputs.email)) {
    userData.em := sha256Hex(lower(trim(inputs.email)))
}
if (not empty(inputs.phone)) {
    userData.ph := sha256Hex(lower(trim(inputs.phone)))
}

let conversion := {
    'eventType': 'custom',
    'eventName': inputs.eventName,
    'eventTime': inputs.eventTime,
    'userData': userData
}
if (not empty(inputs.eventId)) {
    conversion.eventId := inputs.eventId
}

let customData := {}
if (not empty(inputs.conversionValue)) {
    customData.value := toFloat(inputs.conversionValue)
}
if (not empty(inputs.currency)) {
    customData.currency := inputs.currency
}
if (length(keys(customData)) > 0) {
    conversion.customData := customData
}

let res := fetch(f'https://capi.uet.microsoft.com/v1/{inputs.tagId}/events', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.apiToken}',
        'Content-Type': 'application/json'
    },
    'body': {
        'data': [conversion]
    }
})

if (res.status >= 400) {
    throw Error(f'Error from capi.uet.microsoft.com (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'tagId',
            type: 'string',
            label: 'UET Tag ID',
            description:
                'The UET tag ID that conversions are sent to. Find it under Tools > UET tag in Microsoft Advertising.',
            secret: false,
            required: true,
        },
        {
            key: 'apiToken',
            type: 'string',
            label: 'Conversions API token',
            description:
                'The Conversions API auth token for your UET tag. Obtain it in Microsoft Advertising by selecting "Use Conversions API" on the UET tag (pilot program — contact your account manager to enable).',
            secret: true,
            required: true,
        },
    ],
    mapping_templates: [
        {
            name: 'Conversion',
            include_by_default: true,
            filters: {
                events: [],
            },
            inputs_schema: [...build_inputs()],
        },
    ],
}

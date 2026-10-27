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
                'The Microsoft click ID (msclkid) associated with this conversion. It gives the most accurate click attribution, but conversions can also match on hashed email, phone, or external ID when no click ID is available.',
            default: '{person.properties.msclkid ?? person.properties.$initial_msclkid}',
            secret: false,
            required: false,
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
                'Email address for enhanced conversions. It is normalized the way Microsoft requires (lowercased, with dots and any +alias removed from the part before the @) and sent SHA-256 hashed. A value that is already a SHA-256 hash is sent as is. Leave blank to omit.',
            default: '{person.properties.email}',
            secret: false,
            required: false,
        },
        {
            key: 'phone',
            type: 'string',
            label: 'Phone number',
            description:
                'Phone number for enhanced conversions, sent SHA-256 hashed. It must include the country code, for example +1 425 555 1234 or 0044 20 7946 0000. Spaces, dashes, dots, and brackets are removed. A number without a country code is left out, because it cannot be matched. A value that is already a SHA-256 hash is sent as is. Leave blank to omit.',
            default: '{person.properties.phone}',
            secret: false,
            required: false,
        },
        {
            key: 'externalId',
            type: 'string',
            label: 'External ID',
            description:
                'A stable ID for a signed-in user, used for conversion matching. Sent SHA-256 hashed. Leave blank to omit.',
            default: '{person.properties.external_id}',
            secret: false,
            required: false,
        },
        {
            key: 'clientIpAddress',
            type: 'string',
            label: 'IP address',
            description: 'The IP address of the user, used to improve conversion matching.',
            default: '{event.properties.$ip}',
            secret: false,
            required: false,
        },
        {
            key: 'clientUserAgent',
            type: 'string',
            label: 'User agent',
            description: 'The user agent of the browser the conversion happened in.',
            default: '{event.properties.$raw_user_agent}',
            secret: false,
            required: false,
        },
        {
            key: 'eventSourceUrl',
            type: 'string',
            label: 'Source URL',
            description: 'The URL of the page the conversion happened on.',
            default: '{event.properties.$current_url}',
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
// A value that is already a SHA-256 hash is sent as is, so a mapping that hashes upstream is not hashed twice
fn existingSha256(value) {
    let lowered := lower(trim(toString(value)))
    return match(lowered, '^[a-f0-9]{64}$') ? lowered : null
}

// Microsoft removes dots and any +alias from the part before the @ for every email domain, not only Gmail
fn hashEmail(value) {
    let email := lower(trim(toString(value)))
    let parts := splitByString('@', email)
    if (length(parts) != 2) {
        return null
    }
    let localPart := replaceAll(splitByString('+', parts[1])[1], '.', '')
    if (empty(localPart) or empty(parts[2])) {
        return null
    }
    return sha256Hex(f'{localPart}@{parts[2]}')
}

// Microsoft hashes the E.164 form including the leading +. A number without a country code
// is dropped, because guessing the country would send a hash that matches the wrong person or nobody.
fn hashPhone(value) {
    let phone := trim(toString(value))
    for (let separator in [' ', '-', '.', '(', ')']) {
        phone := replaceAll(phone, separator, '')
    }
    if (startsWith(phone, '00')) {
        phone := concat('+', substring(phone, 3))
    }
    if (not match(phone, '^[+][1-9][0-9]{7,14}$')) {
        return null
    }
    return sha256Hex(phone)
}

let userData := {}
if (not empty(inputs.microsoftClickId)) {
    // Microsoft only accepts the click ID as a UUID without hyphens. Other values are sent unchanged,
    // so that a click ID in a format this code does not know is not altered.
    let clickId := trim(toString(inputs.microsoftClickId))
    let clickIdWithoutHyphens := replaceAll(clickId, '-', '')
    userData.msclkid := match(clickIdWithoutHyphens, '^[0-9a-fA-F]{32}$') ? clickIdWithoutHyphens : clickId
}
if (not empty(inputs.email)) {
    let em := existingSha256(inputs.email) ?? hashEmail(inputs.email)
    if (empty(em)) {
        print('\`email\` is not a valid email address. Sending the conversion without it.')
    } else {
        userData.em := em
    }
}
if (not empty(inputs.phone)) {
    let ph := existingSha256(inputs.phone) ?? hashPhone(inputs.phone)
    if (empty(ph)) {
        print('\`phone\` has no country code or is not a valid phone number. Sending the conversion without it.')
    } else {
        userData.ph := ph
    }
}
// An external ID is always hashed, even when it looks like a hash, because a user ID can itself be a hex string
if (not empty(inputs.externalId)) {
    userData.externalId := sha256Hex(trim(toString(inputs.externalId)))
}
// Microsoft can only attribute a conversion that carries at least one identifier;
// IP address and user agent alone are not enough
if (length(keys(userData)) == 0) {
    print('No \`microsoftClickId\`, \`email\`, \`phone\` or \`externalId\` to identify the user with. Skipping...')
    return
}
if (not empty(inputs.clientIpAddress)) {
    userData.clientIpAddress := inputs.clientIpAddress
}
if (not empty(inputs.clientUserAgent)) {
    userData.clientUserAgent := inputs.clientUserAgent
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
// Microsoft rejects the whole conversion when eventSourceUrl is not a valid URL, so app URLs such as
// file:// or capacitor:// are left out instead of being sent
if (match(toString(inputs.eventSourceUrl ?? ''), '^https?://')) {
    conversion.eventSourceUrl := inputs.eventSourceUrl
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
        'data': [conversion],
        'dataProvider': 'posthog'
    }
})

// Validation errors and warnings arrive in error.details. Only the field path and the message are logged,
// because attemptedValue can echo the identifiers that were sent.
let details := typeof(res.body) == 'object' ? res.body.error?.details : null
if (typeof(details) != 'array') {
    details := []
}
if (res.status >= 400) {
    if (empty(details)) {
        throw Error(f'Error from capi.uet.microsoft.com (status {res.status}): {res.body}')
    }
    let problems := arrayStringConcat(arrayMap(detail -> f'{detail.propertyName}: {detail.errorMessage}', details), '; ')
    throw Error(f'Error from capi.uet.microsoft.com (status {res.status}): {problems}')
}
// Microsoft answers 200 when an optional field fails validation, and processes the event without that field
for (let detail in details) {
    if (detail.isWarning) {
        print(f'Microsoft accepted the conversion without \`{detail.propertyName}\`: {detail.errorMessage}')
    }
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

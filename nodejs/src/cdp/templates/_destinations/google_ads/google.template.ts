import { HogFunctionInputSchemaType } from '~/cdp/types'
import { HogFunctionTemplate } from '~/cdp/types'

// Based on https://developers.google.com/google-ads/api/reference/rpc/v24/ClickConversion

const build_inputs = (): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'conversionActionId',
            type: 'integration_field',
            integration_key: 'oauth',
            integration_field: 'google_ads_conversion_action',
            requires_field: 'customerId',
            label: 'Conversion action',
            description: 'The Conversion action associated with this conversion.',
            secret: false,
            required: true,
        },
        {
            key: 'gclid',
            type: 'string',
            label: 'Google Click ID (gclid)',
            description:
                'The Google click ID (gclid) associated with this conversion. Leave blank to attribute via hashed email/phone instead.',
            default: '{person.properties.gclid ?? person.properties.$initial_gclid}',
            secret: false,
            required: false,
        },
        {
            key: 'gbraid',
            type: 'string',
            label: 'Google click ID for iOS app campaigns (gbraid)',
            description:
                'The gbraid from an iOS app campaign click. Sent together with the gclid when both are set. If Google refuses the pair, only the gclid is sent.',
            default: '{person.properties.gbraid ?? person.properties.$initial_gbraid}',
            secret: false,
            required: false,
        },
        {
            key: 'wbraid',
            type: 'string',
            label: 'Google click ID for iOS web campaigns (wbraid)',
            description: 'The wbraid from an iOS web campaign click. Only sent when there is no gclid or gbraid.',
            default: '{person.properties.wbraid ?? person.properties.$initial_wbraid}',
            secret: false,
            required: false,
        },
        {
            key: 'conversionDateTime',
            type: 'string',
            label: 'Conversion Date Time',
            description:
                'The date time at which the conversion occurred. Must be after the click time. The timezone must be specified. The format is "yyyy-mm-dd hh:mm:ss+|-hh:mm", e.g. "2019-01-01 12:32:45-08:00".',
            default: "{formatDateTime(toDateTime(event.timestamp), '%Y-%m-%d %H:%i:%S')}+00:00",
            secret: false,
            required: true,
        },
        {
            key: 'conversionValue',
            type: 'string',
            label: 'Conversion value',
            description: 'The value of the conversion for the advertiser.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'currencyCode',
            type: 'string',
            label: 'Currency code',
            description:
                'Currency associated with the conversion value. This is the ISO 4217 3-character currency code. For example: USD, EUR.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'orderId',
            type: 'string',
            label: 'Order ID',
            description:
                'The order ID associated with the conversion. An order id can only be used for one conversion per conversion action.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Email address',
            description:
                'Email address for enhanced conversions. Used to match the conversion when there is no click ID or Google rejects it. Normalized and sent SHA-256 hashed; leave blank to omit.',
            default: '{person.properties.email}',
            secret: false,
            required: false,
        },
        {
            key: 'phone',
            type: 'string',
            label: 'Phone number',
            description:
                'Phone number for enhanced conversions, including the country code (e.g. +14255551234). Used to match the conversion when there is no click ID or Google rejects it. Normalized to E.164 and sent SHA-256 hashed; numbers without a country code are left out.',
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
    id: 'template-google-ads',
    name: 'Google Ads Conversions',
    description: 'Send conversion events to Google Ads',
    icon_url: '/static/services/google-ads.png',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
// Google rejects these for the click ID only, so the same conversion can still match on hashed email or phone.
let CLICK_ID_REJECTED_CODES := ['UNPARSEABLE_GCLID', 'UNPARSEABLE_GBRAID', 'UNPARSEABLE_WBRAID', 'EXPIRED_EVENT', 'EVENT_NOT_FOUND', 'CONVERSION_PRECEDES_EVENT', 'INVALID_CUSTOMER_FOR_CLICK', 'UNAUTHORIZED_CUSTOMER', 'ONE_PER_CLICK_CONVERSION_ACTION_NOT_PERMITTED_WITH_BRAID']
// Google rejects these for the hashed email or phone only, so the same conversion can still match on the click ID.
let USER_DATA_REJECTED_CODES := ['INVALID_USER_IDENTIFIER', 'UNSUPPORTED_USER_IDENTIFIER', 'CUSTOMER_NOT_ACCEPTED_CUSTOMER_DATA_TERMS', 'CUSTOMER_DATA_POLICY_PROHIBITS_ENHANCED_CONVERSIONS', 'CUSTOMER_NOT_ENABLED_ENHANCED_CONVERSIONS_FOR_LEADS']
let ALREADY_RECORDED_CODES := ['ORDER_ID_ALREADY_IN_USE', 'CLICK_CONVERSION_ALREADY_EXISTS']

fun normalizeEmail(raw) {
    let email := lower(replaceAll(trim(raw), ' ', ''))
    let parts := splitByString('@', email)
    if (length(parts) != 2 or empty(parts[1]) or empty(parts[2])) {
        return null
    }
    if (parts[2] == 'gmail.com' or parts[2] == 'googlemail.com') {
        return f'{replaceAll(parts[1], '.', '')}@{parts[2]}'
    }
    return email
}

fun normalizePhone(raw) {
    let phone := trim(raw)
    for (let separator in [' ', '-', '.', '(', ')']) {
        phone := replaceAll(phone, separator, '')
    }
    // Without a + or 00 prefix the country code is unknown, and guessing one hashes another person's number.
    if (startsWith(phone, '00')) {
        phone := f'+{substring(phone, 3)}'
    }
    if (not match(phone, '^[+][1-9][0-9]{6,14}$')) {
        return null
    }
    return phone
}

fun uploadErrorCodes(res) {
    let codes := []
    for (let detail in res.body.partialFailureError.details ?? []) {
        for (let error in detail.errors ?? []) {
            codes := arrayPushBack(codes, error.errorCode.conversionUploadError ?? error.errorCode.fieldError ?? 'OTHER')
        }
    }
    return codes
}

fun allIn(values, allowed) {
    if (empty(values)) {
        return false
    }
    for (let value in values) {
        if (not has(allowed, value)) {
            return false
        }
    }
    return true
}

fun upload(clickIds, userIdentifiers) {
    let conversion := {
        'conversion_action': f'customers/{splitByString('/', inputs.customerId)[1]}/conversionActions/{inputs.conversionActionId}',
        'conversion_date_time': inputs.conversionDateTime
    }
    for (let key, value in clickIds) {
        conversion[key] := value
    }
    if (not empty(userIdentifiers)) {
        conversion.user_identifiers := userIdentifiers
    }
    if (not empty(inputs.conversionValue)) {
        conversion.conversion_value := inputs.conversionValue
    }
    if (not empty(inputs.currencyCode)) {
        conversion.currency_code := inputs.currencyCode
    }
    if (not empty(inputs.orderId)) {
        conversion.order_id := inputs.orderId
    }

    let res := fetch(f'https://googleads.googleapis.com/v24/customers/{splitByString('/', inputs.customerId)[1]}:uploadClickConversions', {
        'method': 'POST',
        'headers': {
            'Authorization': f'Bearer {inputs.oauth.access_token}',
            'Content-Type': 'application/json',
            'login-customer-id': splitByString('/', inputs.customerId)[2]
        },
        'body': {
            'conversions': [conversion],
            'partialFailure': true
        }
    })

    if (res.status >= 400) {
        throw Error(f'Error from googleads.googleapis.com (status {res.status}): {res.body}')
    }
    return res
}

let userIdentifiers := []
if (not empty(inputs.email)) {
    let email := normalizeEmail(inputs.email)
    if (not empty(email)) {
        userIdentifiers := arrayPushBack(userIdentifiers, {'hashed_email': sha256Hex(email)})
    }
}
if (not empty(inputs.phone)) {
    let phone := normalizePhone(inputs.phone)
    if (not empty(phone)) {
        userIdentifiers := arrayPushBack(userIdentifiers, {'hashed_phone_number': sha256Hex(phone)})
    }
}

// Google accepts a gclid with a gbraid, but never a gbraid with a wbraid.
let clickIds := {}
if (not empty(inputs.gclid)) {
    clickIds.gclid := inputs.gclid
    if (not empty(inputs.gbraid)) {
        clickIds.gbraid := inputs.gbraid
    }
} else if (not empty(inputs.gbraid)) {
    clickIds.gbraid := inputs.gbraid
} else if (not empty(inputs.wbraid)) {
    clickIds.wbraid := inputs.wbraid
}

if (empty(clickIds) and empty(userIdentifiers)) {
    print('No click ID or user identifiers. Skipping...')
    return
}

let res := upload(clickIds, userIdentifiers)
let codes := uploadErrorCodes(res)

// Google recommends sending a gclid with its gbraid, but some accounts still refuse the pair.
if (not empty(clickIds.gclid) and not empty(clickIds.gbraid) and allIn(codes, ['VALUE_MUST_BE_UNSET'])) {
    print('Google refused the gclid and gbraid together. Retrying with the gclid only.')
    clickIds := {'gclid': clickIds.gclid}
    res := upload(clickIds, userIdentifiers)
    codes := uploadErrorCodes(res)
}

if (not empty(clickIds) and not empty(userIdentifiers) and allIn(codes, CLICK_ID_REJECTED_CODES)) {
    print(f'Google rejected the click ID ({arrayStringConcat(codes, ', ')}). Retrying with hashed email/phone only.')
    res := upload({}, userIdentifiers)
    codes := uploadErrorCodes(res)
} else if (not empty(clickIds) and not empty(userIdentifiers) and allIn(codes, USER_DATA_REJECTED_CODES)) {
    print(f'Google rejected the hashed email/phone ({arrayStringConcat(codes, ', ')}). Retrying with the click ID only.')
    res := upload(clickIds, [])
    codes := uploadErrorCodes(res)
}

if (empty(res.body.partialFailureError)) {
    return
}
if (allIn(codes, ['CLICK_NOT_FOUND'])) {
    print('Google could not match the hashed email/phone to an ad click. The conversion was not recorded.')
    return
}
if (allIn(codes, ALREADY_RECORDED_CODES)) {
    print('Google already recorded this conversion. Skipping...')
    return
}
throw Error(f'Error from googleads.googleapis.com (status {res.status}): {res.body.partialFailureError.message}')
`,
    inputs_schema: [
        {
            key: 'oauth',
            type: 'integration',
            integration: 'google-ads',
            label: 'Google Ads account',
            requiredScopes: 'https://www.googleapis.com/auth/adwords https://www.googleapis.com/auth/userinfo.email',
            secret: false,
            required: true,
        },
        {
            key: 'customerId',
            type: 'integration_field',
            integration_key: 'oauth',
            integration_field: 'google_ads_customer_id',
            label: 'Customer ID',
            description: 'ID of your Google Ads Account. This should be 10-digits and in XXX-XXX-XXXX format.',
            secret: false,
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

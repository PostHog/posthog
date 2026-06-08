import { HogFunctionInputSchemaType } from '~/cdp/types'
import { HogFunctionTemplate } from '~/cdp/types'

// Based on https://developers.google.com/data-manager/api/reference/rest/v1/events/ingest
// Google blocks new developer tokens on the Google Ads API uploadClickConversions endpoint
// from June 15, 2026; this template targets the replacement Data Manager API.

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
            description: 'The Google click ID (gclid) associated with this conversion.',
            default: '{person.properties.gclid ?? person.properties.$initial_gclid}',
            secret: false,
            required: true,
        },
        {
            key: 'conversionDateTime',
            type: 'string',
            label: 'Conversion Date Time',
            description:
                'The date time at which the conversion occurred. Must be after the click time. The timezone must be specified. The format is ISO 8601 "yyyy-mm-ddThh:mm:ss+|-hh:mm", e.g. "2019-01-01T12:32:45-08:00".',
            default: "{formatDateTime(toDateTime(event.timestamp), '%Y-%m-%dT%H:%i:%S')}+00:00",
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
if (empty(inputs.gclid)) {
    print('Empty \`gclid\`. Skipping...')
    return
}

let body := {
    'destinations': [
        {
            'operatingAccount': {
                'accountType': 'GOOGLE_ADS',
                'accountId': splitByString('/', inputs.customerId)[1]
            },
            'loginAccount': {
                'accountType': 'GOOGLE_ADS',
                'accountId': splitByString('/', inputs.customerId)[2]
            },
            'productDestinationId': inputs.conversionActionId
        }
    ],
    'events': [
        {
            'eventTimestamp': inputs.conversionDateTime,
            'adIdentifiers': {
                'gclid': inputs.gclid
            }
        }
    ]
}

if (not empty(inputs.conversionValue)) {
    body.events[1].conversionValue := toFloat(inputs.conversionValue)
}
if (not empty(inputs.currencyCode)) {
    body.events[1].currency := inputs.currencyCode
}
if (not empty(inputs.orderId)) {
    body.events[1].transactionId := inputs.orderId
}

let res := fetch('https://datamanager.googleapis.com/v1/events:ingest', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.oauth.access_token}',
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'Error from datamanager.googleapis.com (status {res.status}): {res.body}')
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

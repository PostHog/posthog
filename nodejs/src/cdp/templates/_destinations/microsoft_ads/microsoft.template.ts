import { HogFunctionInputSchemaType } from '~/cdp/types'
import { HogFunctionTemplate } from '~/cdp/types'

// Based on https://learn.microsoft.com/en-us/advertising/campaign-management-service/applyofflineconversions?view=bingads-13
// (REST endpoint: POST /CampaignManagement/v13/OfflineConversions/Apply)

const build_inputs = (): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'conversionName',
            type: 'string',
            label: 'Conversion name',
            description:
                'The name of the offline conversion goal configured in Microsoft Advertising. Conversions are matched to this goal by name, so it must match exactly. Wait at least two hours after creating the goal before sending conversions.',
            secret: false,
            required: true,
        },
        {
            key: 'microsoftClickId',
            type: 'string',
            label: 'Microsoft Click ID (msclkid)',
            description: 'The Microsoft click ID (msclkid) associated with this conversion.',
            default: '{person.properties.msclkid ?? person.properties.$initial_msclkid}',
            secret: false,
            required: true,
        },
        {
            key: 'conversionTime',
            type: 'string',
            label: 'Conversion time',
            description:
                'The date and time at which the conversion occurred, in UTC. Must be after the click time. The format is ISO 8601, e.g. "2019-01-01T12:32:45Z".',
            default: "{formatDateTime(toDateTime(event.timestamp), '%Y-%m-%dT%H:%i:%SZ')}",
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
            key: 'conversionCurrencyCode',
            type: 'string',
            label: 'Currency code',
            description:
                'Currency associated with the conversion value. This is the ISO 4217 3-character currency code. For example: USD, EUR. If empty, the conversion goal default is used.',
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
    description: 'Send offline conversion events to Microsoft Advertising (Bing Ads)',
    icon_url: '/static/services/bing-ads.svg',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
if (empty(inputs.microsoftClickId)) {
    print('Empty \`microsoftClickId\`. Skipping...')
    return
}

let conversion := {
    'MicrosoftClickId': inputs.microsoftClickId,
    'ConversionName': inputs.conversionName,
    'ConversionTime': inputs.conversionTime
}

if (not empty(inputs.conversionValue)) {
    conversion.ConversionValue := toFloat(inputs.conversionValue)
}
if (not empty(inputs.conversionCurrencyCode)) {
    conversion.ConversionCurrencyCode := inputs.conversionCurrencyCode
}

let res := fetch('https://campaign.api.bingads.microsoft.com/CampaignManagement/v13/OfflineConversions/Apply', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.oauth.access_token}',
        'Content-Type': 'application/json',
        'CustomerId': inputs.customerId,
        'CustomerAccountId': inputs.customerAccountId
    },
    'body': {
        'OfflineConversions': [conversion]
    }
})

if (res.status >= 400) {
    throw Error(f'Error from campaign.api.bingads.microsoft.com (status {res.status}): {res.body}')
} else if (not empty(res.body.PartialErrors)) {
    throw Error(f'Error from campaign.api.bingads.microsoft.com (status {res.status}): {res.body.PartialErrors}')
}
`,
    inputs_schema: [
        {
            key: 'oauth',
            type: 'integration',
            integration: 'bing-ads',
            label: 'Microsoft Ads account',
            requiredScopes: 'https://ads.microsoft.com/msads.manage offline_access openid profile',
            secret: false,
            required: true,
        },
        {
            key: 'customerId',
            type: 'string',
            label: 'Customer ID',
            description:
                'The identifier of the manager account (customer) that the account belongs to. Find it under Settings > Accounts and Billing in Microsoft Advertising.',
            secret: false,
            required: true,
        },
        {
            key: 'customerAccountId',
            type: 'string',
            label: 'Account ID',
            description:
                'The identifier of the ad account that owns the conversion goal. Find it under Settings > Accounts and Billing in Microsoft Advertising.',
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

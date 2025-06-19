import { HogFunctionInputSchemaType } from '~/cdp/types'

import { HogFunctionTemplate } from '../../types'

const build_inputs = (multiProductEvent = false): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'eventId',
            type: 'string',
            label: 'Event ID',
            description: 'The ID of the event',
            default: '{event.uuid}',
            secret: false,
            required: true,
        },
        {
            key: 'eventTime',
            type: 'string',
            label: 'Event time',
            description: 'A Unix timestamp in seconds indicating when the actual event occurred',
            default: '{floor(toUnixTimestamp(event.timestamp))}',
            secret: false,
            required: true,
        },
        {
            key: 'eventSourceUrl',
            type: 'string',
            label: 'Event source URL',
            description: 'The URL of the web page where the event took place',
            default: '{event.properties.$current_url}',
            secret: false,
            required: true,
        },
        {
            key: 'actionSource',
            label: 'Action source',
            type: 'choice',
            choices: [
                {
                    label: 'WEB - Conversion was made on your website.',
                    value: 'WEB',
                },
                {
                    label: 'MOBILE_APP - Conversion was made on your mobile app.',
                    value: 'MOBILE_APP',
                },
                {
                    label: 'OFFLINE - Conversion happened in a way that is not listed.',
                    value: 'OFFLINE',
                },
            ],
            description:
                'This field allows you to specify where your conversions occurred. Knowing where your events took place helps ensure your ads go to the right people.',
            default: 'WEB',
            secret: false,
            required: true,
        },
        {
            key: 'customData',
            type: 'dictionary',
            label: 'Custom data',
            description:
                'A map that contains custom data. See this page for options: https://developers.snap.com/api/marketing-api/Conversions-API/Parameters#custom-data-parameters',
            default: {
                value: '{toFloat(event.properties.price ?? event.properties.value ?? event.properties.revenue)}',
                currency: '{event.properties.currency}',
                content_ids: multiProductEvent
                    ? '{arrayMap(x -> x.sku, event.properties.products ?? [])}'
                    : '{event.properties.sku}',
                content_category: multiProductEvent
                    ? '{arrayMap(x -> x.category, event.properties.products ?? [])}'
                    : '{event.properties.category}',
                search_string: '{event.properties.search_string ?? event.properties.query}',
                contents: multiProductEvent
                    ? "{arrayMap(x -> ({'item_price': x.price, 'id': x.sku, 'quantity': x.quantity, 'delivery_category': 'normal'}), event.properties.products ?? [])}"
                    : "{(not empty(event.properties.price) and not empty(event.properties.sku) and not empty(event.properties.quantity) ? [{'item_price': event.properties.price, 'id': event.properties.sku, 'quantity': event.properties.quantity, 'delivery_category': 'normal'}] : [])}",
                num_items: multiProductEvent
                    ? '{arrayReduce((acc, curr) -> acc + curr.quantity, event.properties.products ?? [], 0)}'
                    : '{event.properties.quantity}',
                order_id:
                    '{event.properties.orderId ?? event.properties.transactionId ?? event.properties.transaction_id}',
                event_id: '{event.uuid}',
            },
            secret: false,
            required: true,
        },
    ]
}

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-snapchat-ads',
    name: 'Snapchat Ads Conversions',
    description: 'Send conversion events to Snapchat Ads',
    icon_url: '/static/services/snapchat.png',
    category: ['Advertisement'],
    hog: `
if (empty(inputs.pixelId) or empty(inputs.oauth.access_token)) {
    throw Error('Pixel ID and access token are required')
}

let body := {
    'data': [
        {
            'event_name': inputs.eventType,
            'action_source': inputs.actionSource,
            'event_time': inputs.eventTime,
            'event_source_url': inputs.eventSourceUrl,
            'user_data': {},
            'custom_data': {}
        }
    ]
}

for (let key, value in inputs.userData) {
    if (not empty(value)) {
        body.data.1.user_data[key] := value
    }
}

for (let key, value in inputs.customData) {
    if (not empty(value)) {
        body.data.1.custom_data[key] := value
    }
}

if (not (not empty(body.data.1.user_data.em) or not empty(body.data.1.user_data.ph) or ( not empty(body.data.1.user_data.client_ip_address) and not empty(body.data.1.user_data.client_user_agent) ))) {
    return
}

let res := fetch(f'https://tr.snapchat.com/v3/{inputs.pixelId}/events{inputs.testEventMode ? '/validate' : ''}?access_token={inputs.oauth.access_token}', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from tr.snapchat.com (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'oauth',
            type: 'integration',
            integration: 'snapchat',
            label: 'Snapchat account',
            requiredScopes: 'snapchat-offline-conversions-api snapchat-marketing-api',
            secret: false,
            required: true,
        },
        {
            key: 'pixelId',
            type: 'string',
            label: 'Pixel ID',
            description:
                "You must obtain a Pixel ID to use the Conversions API. If you've already set up a Pixel for your website, we recommend that you use the same Pixel ID for your browser and server events.",
            secret: false,
            required: true,
        },
        {
            key: 'userData',
            type: 'dictionary',
            label: 'User data',
            description:
                'A map that contains customer information data. See this page for options: https://developers.snap.com/api/marketing-api/Conversions-API/Parameters#user-data-parameters',
            default: {
                em: '{sha256Hex(lower(person.properties.email))}',
                ph: "{not empty(person.properties.phone) ? sha256Hex(replaceAll(person.properties.phone, '+', '')) : null}",
                sc_click_id: '{person.properties.sccid ?? person.properties.$initial_sccid}',
                client_user_agent: '{event.properties.$raw_user_agent}',
                fn: '{sha256Hex(lower(person.properties.first_name))}',
                ln: '{sha256Hex(lower(person.properties.last_name))}',
                ct: "{not empty(person.properties.$geoip_city_name) ? sha256Hex(replaceAll(lower(person.properties.$geoip_city_name), ' ', '')) : null}",
                st: '{sha256Hex(lower(person.properties.$geoip_subdivision_1_code))}',
                country: '{sha256Hex(lower(person.properties.$geoip_country_code))}',
                zp: "{not empty (person.properties.$geoip_postal_code) ? sha256Hex(replaceAll(lower(person.properties.$geoip_postal_code), ' ', '')) : null}",
                client_ip_address: '{event.properties.$ip}',
                external_id: '{sha256Hex(person.id)}',
            },
            secret: false,
            required: true,
        },
        {
            key: 'testEventMode',
            type: 'boolean',
            label: 'Test Event Mode',
            description:
                "Use this field to specify that events should be test events rather than actual traffic. You'll want to disable this field when sending real traffic through this integration.",
            default: false,
            secret: false,
            required: false,
        },
    ],
    mapping_templates: [
        {
            name: 'Page viewed',
            include_by_default: true,
            filters: {
                events: [{ id: '$pageview', name: 'Pageview', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'PAGE_VIEW',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Order Completed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Order Completed', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'PURCHASE',
                    required: true,
                },
                ...build_inputs(true),
            ],
        },
        {
            name: 'Checkout Started',
            include_by_default: true,
            filters: {
                events: [{ id: 'Checkout Started', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'START_CHECKOUT',
                    required: true,
                },
                ...build_inputs(true),
            ],
        },
        {
            name: 'Product Added',
            include_by_default: true,
            filters: {
                events: [{ id: 'Product Added', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'ADD_CART',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Payment Info Entered',
            include_by_default: true,
            filters: {
                events: [{ id: 'Payment Info Entered', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'ADD_BILLING',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Promotion Clicked',
            include_by_default: true,
            filters: {
                events: [{ id: 'Promotion Clicked', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'AD_CLICK',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Promotion Viewed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Promotion Viewed', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'AD_VIEW',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Product Added to Wishlist',
            include_by_default: true,
            filters: {
                events: [{ id: 'Product Added to Wishlist', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'ADD_TO_WISHLIST',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Product Viewed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Product Viewed', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'VIEW_CONTENT',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Product List Viewed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Product List Viewed', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'VIEW_CONTENT',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Products Searched',
            include_by_default: true,
            filters: {
                events: [{ id: 'Products Searched', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation',
                    default: 'SEARCH',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
    ],
}

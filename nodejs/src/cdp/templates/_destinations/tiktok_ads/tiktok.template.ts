import { HogFunctionInputSchemaType } from '~/cdp/types'
import { HogFunctionTemplate } from '~/cdp/types'

const build_inputs = (multiProductEvent = false): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'eventId',
            type: 'string',
            label: 'Event ID',
            description: 'The ID of the event.',
            default: '{event.uuid}',
            secret: false,
            required: true,
        },
        {
            key: 'eventTimestamp',
            type: 'string',
            label: 'Event timestamp',
            description: 'A Unix timestamp in seconds indicating when the actual event occurred.',
            default: '{toUnixTimestamp(event.timestamp)}',
            secret: false,
            required: true,
        },
        {
            key: 'propertyProperties',
            type: 'dictionary',
            label: 'Property properties',
            description:
                'A map that contains customer information data. See this page for options: https://business-api.tiktok.com/portal/docs?id=1771101151059969#item-link-properties%20parameters',
            default: {
                content_ids: multiProductEvent
                    ? '{arrayMap(x -> x.sku, event.properties.products ?? [])}'
                    : '{not empty(event.properties.sku) ? [event.properties.sku] : []}',
                contents: multiProductEvent
                    ? "{arrayMap(x -> ({'price': x.price, 'content_id': x.sku, 'content_category': x.category, 'content_name': x.name, 'brand': x.brand}), event.properties.products ?? [])}"
                    : "{(not empty(event.properties.sku) and not empty(event.properties.price) and not empty(event.properties.category) and not empty(event.properties.name) and not empty(event.properties.brand) ? [{'price': event.properties.price, 'content_id': event.properties.sku, 'content_category': event.properties.category, 'content_name': event.properties.name, 'brand': event.properties.brand}] : [])}",
                content_type: 'product',
                currency: "{event.properties.currency ?? 'USD'}",
                value: '{toFloat(event.properties.value ?? event.properties.revenue ?? event.properties.price)}',
                num_items: multiProductEvent
                    ? '{arrayReduce((acc, curr) -> acc + curr.quantity, event.properties.products ?? [], 0)}'
                    : '{event.properties.quantity}',
                search_string: '{event.properties.query}',
                description: '',
                order_id: '{event.properties.order_id}',
                shop_id: '{event.properties.shop_id}',
            },
            secret: false,
            required: true,
        },
        {
            key: 'pageProperties',
            type: 'dictionary',
            label: 'Page properties',
            description:
                'A map that contains page information data. See this page for options: https://business-api.tiktok.com/portal/docs?id=1771101151059969#item-link-page%20parameters',
            default: {
                referrer: '{event.properties.$referrer}',
                url: '{event.properties.$current_url}',
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
    id: 'template-tiktok-ads',
    name: 'TikTok Ads Conversions',
    description: 'Send conversion events to TikTok Ads',
    icon_url: '/static/services/tiktok.png',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
if (empty(inputs.pixelId) or empty(inputs.accessToken)) {
    throw Error('Pixel ID and access token are required')
}

let body := {
    'event_source': 'web',
    'event_source_id': inputs.pixelId,
    'data': [
        {
            'event': inputs.eventName,
            'event_time': inputs.eventTimestamp,
            'event_id': inputs.eventId,
            'user': {},
            'properties': {},
            'page': {}
        }
    ]
}

if (not empty(inputs.testEventCode)) {
    body.test_event_code := inputs.testEventCode
}

for (let key, value in inputs.userProperties) {
    if (not empty(value) or value == '') {
        body.data.1.user[key] := value
    }
}

for (let key, value in inputs.propertyProperties) {
    if (not empty(value)) {
        body.data.1.properties[key] := value
    }
}

for (let key, value in inputs.pageProperties) {
    if (not empty(value)) {
        body.data.1.page[key] := value
    }
}

let res := fetch(f'https://business-api.tiktok.com/open_api/v1.3/event/track/', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Access-Token': inputs.accessToken
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from business-api.tiktok.com (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'accessToken',
            type: 'string',
            label: 'Access token',
            description:
                'Check out this page on how to obtain such a token: https://business-api.tiktok.com/portal/docs?id=1771101027431425',
            secret: true,
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
            key: 'userProperties',
            type: 'dictionary',
            label: 'User properties',
            description:
                'A map that contains customer information data. See this page for options: https://business-api.tiktok.com/portal/docs?id=1771101151059969#item-link-user%20parameters',
            default: {
                email: "{not empty(person.properties.email) ? sha256Hex(lower(person.properties.email)) : ''}",
                first_name:
                    "{not empty(person.properties.first_name) ? sha256Hex(lower(person.properties.first_name)) : ''}",
                last_name:
                    "{not empty(person.properties.last_name) ? sha256Hex(lower(person.properties.last_name)) : ''}",
                phone: "{not empty(person.properties.phone) ? sha256Hex(person.properties.phone) : ''}",
                external_id: "{not empty(person.id) ? sha256Hex(person.id) : ''}",
                city: "{not empty(person.properties.$geoip_city_name) ? replaceAll(lower(person.properties.$geoip_city_name), ' ', '') : null}",
                state: '{lower(person.properties.$geoip_subdivision_1_code)}',
                country: '{lower(person.properties.$geoip_country_code)}',
                zip_code:
                    "{not empty (person.properties.$geoip_postal_code) ? sha256Hex(replaceAll(lower(person.properties.$geoip_postal_code), ' ', '')) : null}",
                ttclid: '{person.properties.ttclid ?? person.properties.$initial_ttclid}',
                ip: '{event.properties.$ip}',
                user_agent: '{event.properties.$raw_user_agent}',
            },
            secret: false,
            required: true,
        },
        {
            key: 'testEventCode',
            type: 'string',
            label: 'Test Event Code',
            description:
                "Use this field to specify that events should be test events rather than actual traffic. You'll want to remove your Test Event Code when sending real traffic through this integration.",
            default: '',
            secret: false,
            required: false,
        },
    ],
    mapping_templates: [
        {
            name: 'Page Viewed',
            include_by_default: true,
            filters: {
                events: [{ id: '$pageview', name: 'Pageview', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'Pageview',
                    secret: false,
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
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'AddPaymentInfo',
                    secret: false,
                    required: true,
                },
                ...build_inputs(),
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
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'AddToCart',
                    secret: false,
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
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'AddToWishlist',
                    secret: false,
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Product Clicked',
            include_by_default: true,
            filters: {
                events: [{ id: 'Product Clicked', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'ClickButton',
                    secret: false,
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Order Placed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Order Placed', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'PlaceAnOrder',
                    secret: false,
                    required: true,
                },
                ...build_inputs(true),
            ],
        },
        {
            name: 'Signed Up',
            include_by_default: true,
            filters: {
                events: [{ id: 'Signed Up', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'CompleteRegistration',
                    secret: false,
                    required: true,
                },
                ...build_inputs(),
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
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'InitiateCheckout',
                    secret: false,
                    required: true,
                },
                ...build_inputs(true),
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
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'CompletePayment',
                    secret: false,
                    required: true,
                },
                ...build_inputs(true),
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
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'Search',
                    secret: false,
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
                    key: 'eventName',
                    type: 'string',
                    label: 'Event name',
                    description: 'A standard event or custom event name.',
                    default: 'ViewContent',
                    secret: false,
                    required: true,
                },
                ...build_inputs(),
            ],
        },
    ],
}

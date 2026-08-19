import { HogFunctionInputSchemaType } from '~/cdp/types'
import { HogFunctionTemplate } from '~/cdp/types'

const build_inputs = (eventName: string, customData: Record<string, any>): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'eventName',
            type: 'string',
            label: 'Event name',
            description: 'A standard event or custom event name.',
            default: eventName,
            secret: false,
            required: true,
        },
        {
            key: 'customData',
            type: 'dictionary',
            label: 'Custom data',
            description:
                'A map that contains custom data. See this page for options: https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/custom-data',
            default: customData,
            secret: false,
            required: true,
        },
    ]
}

const currency = "{event.properties.currency ?? 'USD'}"
const value =
    "{empty(event.properties.value) and empty(event.properties.revenue) and empty(event.properties.price) ? '' : toFloat(event.properties.value ?? event.properties.revenue ?? event.properties.price)}"
const singleContentIds =
    '{not empty(event.properties.sku) ? [event.properties.sku] : (not empty(event.properties.product_id) ? [event.properties.product_id] : [])}'
const singleContents =
    "{not empty(event.properties.quantity) and (not empty(event.properties.sku) or not empty(event.properties.product_id)) ? [{'id': event.properties.sku ?? event.properties.product_id, 'quantity': event.properties.quantity, 'item_price': event.properties.price}] : []}"
const multiContentIds = '{arrayMap(x -> x.sku ?? x.product_id, event.properties.products ?? [])}'
const multiContents =
    "{arrayMap(x -> ({'id': x.sku ?? x.product_id, 'quantity': x.quantity, 'item_price': x.price}), arrayFilter(x -> (not empty(x.sku) or not empty(x.product_id)) and not empty(x.quantity), event.properties.products ?? []))}"
const numItems = '{arrayReduce((acc, curr) -> acc + curr.quantity, event.properties.products ?? [], 0)}'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-meta-ads',
    name: 'Meta Ads Conversions',
    description: 'Send conversion events to Meta Ads',
    icon_url: '/static/services/meta-ads.png',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
if (empty(inputs.pixelId) or empty(inputs.accessToken)) {
    throw Error('Pixel ID and access token are required')
}

let body := {
    'data': [
        {
            'event_name': inputs.eventName,
            'event_id': inputs.eventId,
            'event_time': inputs.eventTime,
            'action_source': inputs.actionSource,
            'user_data': {},
            'custom_data': {}
        }
    ],
    'access_token': inputs.accessToken
}

if (not empty(inputs.testEventCode)) {
    body.test_event_code := inputs.testEventCode
}

if (not empty(inputs.eventSourceUrl)) {
    body.data.1.event_source_url := inputs.eventSourceUrl
}

// Helper function to parse JSON arrays from string values
fn parseValueIfArray(value) {
    if (typeof(value) == 'string') {
        let trimmed := trim(value)
        if (startsWith(trimmed, '[')) {
            try {
                return jsonParse(trimmed)
            } catch {
                return value
            }
        }
    }
    return value
}

for (let key, value in inputs.userData) {
    if (not empty(value)) {
        body.data.1.user_data[key] := parseValueIfArray(value)
    }
}

for (let key, value in inputs.customData) {
    if (not empty(value)) {
        body.data.1.custom_data[key] := parseValueIfArray(value)
    }
}

let res := fetch(f'https://graph.facebook.com/v25.0/{inputs.pixelId}/events', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from graph.facebook.com (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'accessToken',
            type: 'string',
            label: 'Access token',
            description:
                'Check out this page on how to obtain such a token: https://developers.facebook.com/docs/marketing-api/conversions-api/get-started',
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
            key: 'eventId',
            type: 'string',
            label: 'Event ID',
            description: 'The ID of the event.',
            default: '{event.uuid}',
            secret: false,
            required: true,
        },
        {
            key: 'eventSourceUrl',
            type: 'string',
            label: 'Event source URL',
            description: 'The URL of the page where the event occurred.',
            default: '{event.properties.$current_url}',
            secret: false,
            required: false,
        },
        {
            key: 'eventTime',
            type: 'string',
            label: 'Event time',
            description:
                'A Unix timestamp in seconds indicating when the actual event occurred. You must send this date in GMT time zone.',
            default: '{toInt(toUnixTimestamp(event.timestamp))}',
            secret: false,
            required: true,
        },
        {
            key: 'actionSource',
            label: 'Action source',
            type: 'choice',
            choices: [
                { label: 'Email - Conversion happened over email.', value: 'email' },
                { label: 'Website - Conversion was made on your website.', value: 'website' },
                { label: 'App - Conversion was made on your mobile app.', value: 'app' },
                { label: 'Phone call - Conversion was made over the phone.', value: 'phone_call' },
                {
                    label: 'Chat - Conversion was made via a messaging app, SMS, or online messaging feature.',
                    value: 'chat',
                },
                {
                    label: 'Physical store - Conversion was made in person at your physical store.',
                    value: 'physical_store',
                },
                {
                    label: 'System generated - Conversion happened automatically, for example, a subscription renewal that is set to auto-pay each month.',
                    value: 'system_generated',
                },
                {
                    label: 'Business messaging - Conversion was made from ads that click to Messenger, Instagram or WhatsApp.',
                    value: 'business_messaging',
                },
                { label: 'Other - Conversion happened in a way that is not listed.', value: 'other' },
            ],
            description:
                'This field allows you to specify where your conversions occurred. Knowing where your events took place helps ensure your ads go to the right people.',
            default: 'website',
            secret: false,
            required: true,
        },
        {
            key: 'userData',
            type: 'dictionary',
            label: 'User data',
            description:
                'A map that contains customer information data. See this page for options: https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters',
            default: {
                em: '{sha256Hex(lower(person.properties.email))}',
                fn: '{sha256Hex(lower(person.properties.first_name))}',
                ln: '{sha256Hex(lower(person.properties.last_name))}',
                fbc: "{match(person.properties.fbclid ?? person.properties.$initial_fbclid ?? '', '^fb[.][0-9]+[.][0-9]+[.][A-Za-z0-9_-]+$') ? person.properties.fbclid ?? person.properties.$initial_fbclid : (match(person.properties.fbclid ?? person.properties.$initial_fbclid ?? '', '^[A-Za-z0-9_-]+$') ? f'fb.1.{toUnixTimestampMilli(now())}.{person.properties.fbclid ?? person.properties.$initial_fbclid}' : '')}",
                client_user_agent: '{event.properties.$raw_user_agent}',
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
            filters: { events: [{ id: '$pageview', name: 'Pageview', type: 'events' }] },
            inputs_schema: build_inputs('PageView', {}),
        },
        {
            name: 'Product Viewed',
            include_by_default: true,
            filters: { events: [{ id: 'Product Viewed', type: 'events' }] },
            inputs_schema: build_inputs('ViewContent', {
                currency,
                value,
                content_type: 'product',
                content_ids: singleContentIds,
                contents: singleContents,
                content_name: '{event.properties.name}',
                content_category: '{event.properties.category}',
            }),
        },
        {
            name: 'Products Searched',
            include_by_default: true,
            filters: { events: [{ id: 'Products Searched', type: 'events' }] },
            inputs_schema: build_inputs('Search', {
                search_string: '{event.properties.query}',
                content_ids: singleContentIds,
                content_category: '{event.properties.category}',
            }),
        },
        {
            name: 'Product Added',
            include_by_default: true,
            filters: { events: [{ id: 'Product Added', type: 'events' }] },
            inputs_schema: build_inputs('AddToCart', {
                currency,
                value,
                content_type: 'product',
                content_ids: singleContentIds,
                contents: singleContents,
                content_name: '{event.properties.name}',
                content_category: '{event.properties.category}',
            }),
        },
        {
            name: 'Checkout Started',
            include_by_default: true,
            filters: { events: [{ id: 'Checkout Started', type: 'events' }] },
            inputs_schema: build_inputs('InitiateCheckout', {
                currency,
                value,
                content_type: 'product',
                content_ids: multiContentIds,
                contents: multiContents,
                num_items: numItems,
            }),
        },
        {
            name: 'Order Completed',
            include_by_default: true,
            filters: { events: [{ id: 'Order Completed', type: 'events' }] },
            inputs_schema: build_inputs('Purchase', {
                currency,
                value,
                content_type: 'product',
                content_ids: multiContentIds,
                contents: multiContents,
                num_items: numItems,
                order_id: '{event.properties.order_id}',
            }),
        },
        {
            name: 'Lead Generated',
            include_by_default: true,
            filters: { events: [{ id: 'Lead Generated', type: 'events' }] },
            inputs_schema: build_inputs('Lead', { currency, value }),
        },
        {
            name: 'Signed Up',
            include_by_default: true,
            filters: { events: [{ id: 'Signed Up', type: 'events' }] },
            inputs_schema: build_inputs('CompleteRegistration', { currency, value }),
        },
    ],
}

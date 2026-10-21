import { HogFunctionInputSchemaType, HogFunctionTemplate } from '~/cdp/types'

// Based on https://developers.pinterest.com/docs/api/v5/events-create

const EVENT_NAMES: { value: string; label: string }[] = [
    { value: 'add_payment_info', label: 'Add payment info' },
    { value: 'add_to_cart', label: 'Add to cart' },
    { value: 'add_to_wishlist', label: 'Add to wishlist' },
    { value: 'app_install', label: 'App install' },
    { value: 'app_open', label: 'App open' },
    { value: 'checkout', label: 'Checkout' },
    { value: 'contact', label: 'Contact' },
    { value: 'custom', label: 'Custom' },
    { value: 'customize_product', label: 'Customize product' },
    { value: 'find_location', label: 'Find location' },
    { value: 'initiate_checkout', label: 'Initiate checkout' },
    { value: 'lead', label: 'Lead' },
    { value: 'page_visit', label: 'Page visit' },
    { value: 'schedule', label: 'Schedule' },
    { value: 'search', label: 'Search' },
    { value: 'signup', label: 'Sign up' },
    { value: 'start_trial', label: 'Start trial' },
    { value: 'submit_application', label: 'Submit application' },
    { value: 'subscribe', label: 'Subscribe' },
    { value: 'view_category', label: 'View category' },
    { value: 'view_content', label: 'View content' },
    { value: 'watch_video', label: 'Watch video' },
]

const build_inputs = (eventName: string, customData: Record<string, string>): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'eventName',
            type: 'choice',
            label: 'Event name',
            description:
                'The Pinterest conversion event. For an event Pinterest does not list, choose "Custom". See https://developers.pinterest.com/docs/api/v5/events-create',
            choices: EVENT_NAMES,
            default: eventName,
            secret: false,
            required: true,
        },
        {
            key: 'customData',
            type: 'dictionary',
            label: 'Custom data',
            description:
                'Event details such as value, currency and products. Add any other key Pinterest accepts, for example content_name or opt_out_type. Empty values are left out. See https://developers.pinterest.com/docs/api/v5/events-create',
            default: customData,
            secret: false,
            required: false,
        },
    ]
}

const currency = '{event.properties.currency}'
const value = '{event.properties.value ?? event.properties.revenue ?? event.properties.price}'
const singleContentIds =
    '{not empty(event.properties.sku) ? [event.properties.sku] : (not empty(event.properties.product_id) ? [event.properties.product_id] : [])}'
const singleContents =
    "{not empty(event.properties.sku) or not empty(event.properties.product_id) ? [{'id': not empty(event.properties.sku) ? event.properties.sku : event.properties.product_id, 'item_price': event.properties.price, 'quantity': event.properties.quantity, 'item_name': event.properties.name, 'item_brand': event.properties.brand, 'item_category': event.properties.category}] : []}"
const multiContentIds =
    '{arrayMap(x -> not empty(x.sku) ? x.sku : x.product_id, arrayFilter(x -> not empty(x.sku) or not empty(x.product_id), event.properties.products ?? []))}'
const multiContents =
    "{arrayMap(x -> ({'id': not empty(x.sku) ? x.sku : x.product_id, 'item_price': x.price, 'quantity': x.quantity, 'item_name': x.name, 'item_brand': x.brand, 'item_category': x.category}), arrayFilter(x -> not empty(x.sku) or not empty(x.product_id), event.properties.products ?? []))}"
const multiNumItems =
    '{not empty(event.properties.products) ? arrayReduce((acc, curr) -> acc + toInt(curr.quantity ?? 1), event.properties.products, 0) : null}'

const singleProduct = {
    currency,
    value,
    content_ids: singleContentIds,
    contents: singleContents,
    num_items: '{event.properties.quantity}',
    content_name: '{event.properties.name}',
    content_brand: '{event.properties.brand}',
    content_category: '{event.properties.category}',
}

const multiProduct = {
    currency,
    value,
    content_ids: multiContentIds,
    contents: multiContents,
    num_items: multiNumItems,
}

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-pinterest-ads',
    name: 'Pinterest Ads Conversions',
    description: 'Send conversion events to Pinterest Ads',
    icon_url: '/static/services/pinterest.com.png',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
if (empty(inputs.adAccountId) or empty(inputs.conversionToken)) {
    throw Error('Ad account ID and conversion token are required')
}

let HASHED_USER_KEYS := ['em', 'ph', 'fn', 'ln', 'ct', 'st', 'zp', 'country', 'external_id', 'hashed_maids', 'ge', 'db']

fn normalize(key, value) {
    let normalized := lower(trim(toString(value)))
    if (key == 'ph') {
        for (let symbol in ['+', '-', ' ', '(', ')', '.']) {
            normalized := replaceAll(normalized, symbol, '')
        }
    } else if (key == 'ct') {
        for (let symbol in [' ', '.', ',', '-', '\\'']) {
            normalized := replaceAll(normalized, symbol, '')
        }
    } else if (key == 'zp') {
        normalized := replaceAll(normalized, ' ', '')
    }
    return normalized
}

// Pinterest takes a list of hashes per field. A value that is already a SHA-256 hash is sent as is,
// so a mapping that hashes before sending does not get hashed twice.
fn hashAll(key, value) {
    let hashes := []
    for (let item in (typeof(value) == 'array' ? value : [value])) {
        let normalized := empty(item) ? '' : normalize(key, item)
        if (not empty(normalized)) {
            hashes := arrayPushBack(hashes, match(normalized, '^[a-f0-9]{64}$') ? normalized : sha256Hex(normalized))
        }
    }
    return hashes
}

fn cleanContent(item) {
    let cleaned := {}
    for (let key, value in item) {
        if ((key == 'item_price' or key == 'id') and not empty(value)) {
            cleaned[key] := toString(value)
        } else if (key == 'quantity' and not empty(value)) {
            cleaned[key] := toInt(value)
        } else if (not empty(value)) {
            cleaned[key] := value
        }
    }
    return cleaned
}

let payload := {
    'event_name': inputs.eventName,
    'action_source': inputs.actionSource,
    'event_time': toInt(inputs.eventTime),
    'event_id': toString(inputs.eventId),
    'user_data': {}
}

if (not empty(inputs.eventSourceUrl)) {
    payload.event_source_url := inputs.eventSourceUrl
}

for (let key, value in inputs.userData) {
    if (has(HASHED_USER_KEYS, key)) {
        let hashes := hashAll(key, value)
        if (not empty(hashes)) {
            payload.user_data[key] := hashes
        }
    } else if (not empty(value)) {
        payload.user_data[key] := toString(value)
    }
}

fn cleanCustomValue(key, value) {
    if (key == 'value' or key == 'predicted_ltv') {
        return toString(value)
    } else if (key == 'num_items') {
        return toInt(value)
    } else if (key == 'content_ids') {
        let ids := []
        for (let id in (typeof(value) == 'array' ? value : [value])) {
            if (not empty(id)) {
                ids := arrayPushBack(ids, toString(id))
            }
        }
        return ids
    } else if (key == 'contents') {
        let contents := []
        for (let item in value) {
            let cleaned := cleanContent(item)
            if (not empty(cleaned)) {
                contents := arrayPushBack(contents, cleaned)
            }
        }
        return contents
    }
    return value
}

let customData := {}
for (let key, value in inputs.customData) {
    let cleaned := empty(value) ? null : cleanCustomValue(key, value)
    if (not empty(cleaned)) {
        customData[key] := cleaned
    }
}
if (not empty(customData)) {
    payload.custom_data := customData
}

let userData := payload.user_data
if (empty(userData.em) and empty(userData.hashed_maids) and (empty(userData.client_ip_address) or empty(userData.client_user_agent))) {
    print('Skipping event: Pinterest needs an email (em), a mobile ad ID (hashed_maids), or both an IP address and a user agent.')
    return
}

let res := fetch(f'https://api.pinterest.com/v5/ad_accounts/{inputs.adAccountId}/events{inputs.testMode ? '?test=true' : ''}', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.conversionToken}',
        'Content-Type': 'application/json',
    },
    'body': {'data': [payload]}
})

if (res.status >= 400) {
    throw Error(f'Error from api.pinterest.com (status {res.status}): {res.body}')
}

// Pinterest answers 200 even when it rejects an event, and reports the rejection per event.
let result := typeof(res.body) == 'object' and not empty(res.body.events) ? res.body.events[1] : null
if (result?.status == 'failed') {
    throw Error(f'Pinterest rejected the event: {result.error_message}')
}
if (not empty(result?.warning_message)) {
    print(f'Pinterest accepted the event with a warning: {result.warning_message}')
}
`,
    inputs_schema: [
        {
            key: 'adAccountId',
            type: 'string',
            label: 'Ad account ID',
            description:
                'The ID of your Pinterest ad account. See https://help.pinterest.com/en/business/article/conversions-api',
            secret: false,
            required: true,
        },
        {
            key: 'conversionToken',
            type: 'string',
            label: 'Conversion token',
            description:
                'The conversion access token generated in Pinterest Ads Manager, under Conversions. See https://help.pinterest.com/en/business/article/conversions-api',
            secret: true,
            required: true,
        },
        {
            key: 'actionSource',
            type: 'choice',
            label: 'Action source',
            description: 'Where the conversion happened.',
            choices: [
                { label: 'Web', value: 'web' },
                { label: 'Android app', value: 'app_android' },
                { label: 'iOS app', value: 'app_ios' },
                { label: 'Offline', value: 'offline' },
            ],
            default: 'web',
            secret: false,
            required: true,
        },
        {
            key: 'eventId',
            type: 'string',
            label: 'Event ID',
            description:
                'A unique ID for the event. Pinterest uses it to deduplicate events sent by both the Pinterest tag and the Conversions API, so use the same ID in both.',
            default: '{event.uuid}',
            secret: false,
            required: true,
        },
        {
            key: 'eventTime',
            type: 'string',
            label: 'Event time',
            description: 'A Unix timestamp in seconds of when the event happened.',
            default: '{toInt(toUnixTimestamp(event.timestamp))}',
            secret: false,
            required: true,
        },
        {
            key: 'eventSourceUrl',
            type: 'string',
            label: 'Event source URL',
            description: 'The URL of the page where the event happened.',
            default: '{event.properties.$current_url}',
            secret: false,
            required: false,
        },
        {
            key: 'userData',
            type: 'dictionary',
            label: 'User data',
            description:
                'Customer information used for matching. Enter raw values: em, ph, fn, ln, ct, st, zp, country, external_id, hashed_maids, ge and db are lowercased, trimmed and SHA-256 hashed before sending. Empty values are left out. Pinterest needs em, hashed_maids, or both client_ip_address and client_user_agent. See https://developers.pinterest.com/docs/api/v5/events-create',
            default: {
                em: '{person.properties.email}',
                ph: '{person.properties.phone}',
                fn: '{person.properties.first_name}',
                ln: '{person.properties.last_name}',
                ct: '{person.properties.$geoip_city_name}',
                st: '{person.properties.$geoip_subdivision_1_code}',
                zp: '{person.properties.$geoip_postal_code}',
                country: '{person.properties.$geoip_country_code}',
                external_id: '{person.id}',
                client_ip_address: '{event.properties.$ip}',
                client_user_agent: '{event.properties.$raw_user_agent}',
                click_id: '{person.properties.epik ?? person.properties.$initial_epik}',
            },
            secret: false,
            required: true,
        },
        {
            key: 'testMode',
            type: 'boolean',
            label: 'Test mode',
            description:
                'Send events as test events. Pinterest validates them and shows them under Test events in Ads Manager, but does not record them. Turn this off to send real traffic.',
            default: false,
            secret: false,
            required: false,
        },
    ],
    mapping_templates: [
        {
            name: 'Page viewed',
            include_by_default: true,
            filters: { events: [{ id: '$pageview', name: 'Pageview', type: 'events' }] },
            inputs_schema: build_inputs('page_visit', {}),
        },
        {
            name: 'Product viewed',
            include_by_default: true,
            filters: { events: [{ id: 'Product Viewed', type: 'events' }] },
            inputs_schema: build_inputs('view_content', singleProduct),
        },
        {
            name: 'Product list viewed',
            include_by_default: true,
            filters: { events: [{ id: 'Product List Viewed', type: 'events' }] },
            inputs_schema: build_inputs('view_category', {
                content_category: '{event.properties.category}',
                content_ids: multiContentIds,
            }),
        },
        {
            name: 'Products searched',
            include_by_default: true,
            filters: { events: [{ id: 'Products Searched', type: 'events' }] },
            inputs_schema: build_inputs('search', {
                search_string: '{event.properties.query ?? event.properties.search_string}',
            }),
        },
        {
            name: 'Product added',
            include_by_default: true,
            filters: { events: [{ id: 'Product Added', type: 'events' }] },
            inputs_schema: build_inputs('add_to_cart', singleProduct),
        },
        {
            name: 'Product added to wishlist',
            include_by_default: true,
            filters: { events: [{ id: 'Product Added to Wishlist', type: 'events' }] },
            inputs_schema: build_inputs('add_to_wishlist', singleProduct),
        },
        {
            name: 'Checkout started',
            include_by_default: true,
            filters: { events: [{ id: 'Checkout Started', type: 'events' }] },
            inputs_schema: build_inputs('initiate_checkout', multiProduct),
        },
        {
            name: 'Payment info entered',
            include_by_default: true,
            filters: { events: [{ id: 'Payment Info Entered', type: 'events' }] },
            inputs_schema: build_inputs('add_payment_info', multiProduct),
        },
        {
            name: 'Order completed',
            include_by_default: true,
            filters: { events: [{ id: 'Order Completed', type: 'events' }] },
            inputs_schema: build_inputs('checkout', {
                ...multiProduct,
                order_id: '{event.properties.order_id ?? event.properties.orderId ?? event.properties.transaction_id}',
            }),
        },
        {
            name: 'Signed up',
            include_by_default: true,
            filters: { events: [{ id: 'Signed Up', type: 'events' }] },
            inputs_schema: build_inputs('signup', {}),
        },
        {
            name: 'Lead generated',
            include_by_default: true,
            filters: { events: [{ id: 'Lead Generated', type: 'events' }] },
            inputs_schema: build_inputs('lead', { currency, value }),
        },
    ],
}

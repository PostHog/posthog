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

// Meta's _fbc cookie value, `fb.<subdomainIndex>.<clickTimeMs>.<fbclid>`. Candidates in order: a
// value the event carries, a value the site stores on the person, and the $fbc PostHog stamps when it
// sees the fbclid. The code sends the newest one Meta would accept. An fbclid on this event only
// applies when none of them is set, because a click already dated must not come back redated.
const fbc =
    "{not empty(event.properties.fbc) or not empty(person.properties.fbc) or not empty(person.properties.$fbc) ? [event.properties.fbc, person.properties.fbc, person.properties.$fbc] : (not empty(event.properties.fbclid) ? f'fb.1.{toUnixTimestampMilli(event.timestamp)}.{event.properties.fbclid}' : '')}"

const NINETY_DAYS_MS = 90 * 24 * 60 * 60 * 1000
const CLOCK_SKEW_TOLERANCE_MS = 5 * 60 * 1000

// Meta's _fbp cookie value, `fb.<subdomainIndex>.<creationTimeMs>.<randomNumber>`. It identifies a
// browser rather than a click, so PostHog cannot derive it. Candidates in order: values the event
// carries, then values on the person, each first the site's own and then the $fbp the SDK reads
// from the cookie the pixel mints. The code sends the first well-formed one.
const fbp = '{[event.properties.fbp, event.properties.$fbp, person.properties.fbp, person.properties.$fbp]}'

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

// Hog's trim() strips only a literal ASCII space, so a tab or line break survives it and reaches
// hash detection or normalization unstripped. This strips every POSIX whitespace character from
// both ends instead, and every normalization below uses it in trim()'s place.
fn trimSpace(value) {
    return extractRegex(toString(value), '(?s:[^[:space:]](?:.*[^[:space:]])?)')
}

// Meta expects the full address of the page the event happened on, so anything else is left out
let sourceUrl := typeof(inputs.eventSourceUrl) == 'string' ? trimSpace(inputs.eventSourceUrl) : ''
if (match(sourceUrl, '^(?i:https?)://[^/?#[:space:]]+([/?#][^[:space:]]*)?\$')) {
    body.data.1.event_source_url := sourceUrl
}

// Helper function to parse JSON arrays from string values
fn parseValueIfArray(value) {
    if (typeof(value) == 'string') {
        let trimmed := trimSpace(value)
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

// Meta rejects an ad click older than 90 days, the lifetime of the pixel's _fbc cookie, so a stale
// click is dropped instead of sent. The value states its own click time, in segment 3. Meta's
// parameter builder library appends a fifth segment, which stays on the value it sends back.
fn freshClickId(value) {
    if (typeof(value) != 'string') {
        return null
    }
    let trimmed := trimSpace(value)
    if (not match(trimmed, '^fb[.][0-9]+[.][0-9]+[.][A-Za-z0-9_-]+([.][A-Za-z0-9_-]+)?\$')) {
        return null
    }
    // A click cannot precede the conversion it caused. The tolerance holds a click and the pageview
    // that reports it, stamped from one browser clock, in either order.
    let ageMs := toUnixTimestampMilli(event.timestamp) - toFloat(splitByString('.', trimmed)[3])
    if (ageMs < ${-CLOCK_SKEW_TOLERANCE_MS} or ageMs >= ${NINETY_DAYS_MS}) {
        return null
    }
    return trimmed
}

// The newest valid click wins, so a stale or malformed value cannot hide a valid one behind it.
// On a tie, the earlier candidate wins.
fn newestClickId(value) {
    let newest := null
    let newestTime := null
    for (let candidate in (typeof(value) == 'array' ? value : [value])) {
        let fresh := freshClickId(candidate)
        if (fresh != null) {
            let clickTime := toFloat(splitByString('.', fresh)[3])
            if (newestTime == null or clickTime > newestTime) {
                newest := fresh
                newestTime := clickTime
            }
        }
    }
    return newest
}

// The first well-formed browser ID wins. It is sent as is, never hashed or regenerated.
fn firstBrowserId(value) {
    for (let candidate in (typeof(value) == 'array' ? value : [value])) {
        if (typeof(candidate) == 'string') {
            let trimmed := trimSpace(candidate)
            if (match(trimmed, '^fb[.][0-9]+[.][0-9]+[.][0-9]+([.][A-Za-z0-9_-]+)?\$')) {
                return trimmed
            }
        }
    }
    return null
}

let HASHED_USER_KEYS := ['em', 'ph', 'fn', 'ln', 'ge', 'db', 'ct', 'st', 'zp', 'country']

// No real name, city, state, postal code or phone number is this long. A value past this length
// is dropped before the per-character loop below, so an oversized property cannot run it long
// enough to exhaust the function's execution budget.
let MAX_NORMALIZED_FIELD_LENGTH := 255

// A real person has no reason to carry more than a handful of emails or phone numbers. Hashing is
// capped at this many list items, so a very long list cannot exhaust the execution budget either.
let MAX_USER_DATA_LIST_LENGTH := 50

// splitByString splits on UTF-16 code units, so a character outside the Basic Multilingual Plane
// arrives as two halves that each fail to match any character. They are joined before the check.
fn keepMatching(value, pattern) {
    if (length(value) > MAX_NORMALIZED_FIELD_LENGTH) {
        return ''
    }
    let kept := ''
    let pending := ''
    for (let char in splitByString('', value)) {
        let token := char
        if (not empty(pending)) {
            token := concat(pending, char)
            pending := ''
        } else if (not empty(char) and not match(char, '^(?s:.)\$')) {
            pending := char
            token := ''
        }
        if (not empty(token) and match(token, pattern)) {
            kept := concat(kept, token)
        }
    }
    return kept
}

fn normalizeCountry(value) {
    let normalized := lower(trimSpace(value))
    return match(normalized, '^[a-z]{2}\$') ? normalized : ''
}

// inputs.userData.country can hold a plain code, a list of codes, or an already hashed value, since
// it goes through the same hashing loop as every other field. The ZIP+4 rule below only needs to
// tell United States apart from everything else, so this recognizes 'us' in each of those shapes.
fn isUnitedStates(value) {
    let candidate := parseValueIfArray(value)
    if (typeof(candidate) == 'array') {
        candidate := candidate[1]
    }
    let normalized := lower(trimSpace(candidate))
    return normalized == 'us' or normalized == sha256Hex('us')
}

fn pad2(value) {
    return length(value) == 1 ? concat('0', value) : value
}

fn isValidDate(year, month, day) {
    let y := toInt(year)
    let m := toInt(month)
    let d := toInt(day)
    return y != null and m != null and d != null and m >= 1 and m <= 12 and d >= 1 and d <= 31
}

// Meta requires the date of birth as YYYYMMDD, but a raw value can put the year first or last. A
// value with no separator is assumed already in that order. One with a separator is read by where
// its 4-digit year sits, then its month and day are validated and reordered if needed.
fn normalizeDateOfBirth(value) {
    if (match(value, '^[0-9]{8}\$')) {
        return isValidDate(substring(value, 1, 4), substring(value, 5, 2), substring(value, 7, 2)) ? value : ''
    } else if (match(value, '^[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}\$')) {
        let year := extractRegex(value, '^([0-9]{4})')
        let month := pad2(extractRegex(value, '^[0-9]{4}[-/.]([0-9]{1,2})[-/.]'))
        let day := pad2(extractRegex(value, '[-/.]([0-9]{1,2})\$'))
        return isValidDate(year, month, day) ? concat(year, month, day) : ''
    } else if (match(value, '^[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}\$')) {
        let month := pad2(extractRegex(value, '^([0-9]{1,2})[-/.]'))
        let day := pad2(extractRegex(value, '^[0-9]{1,2}[-/.]([0-9]{1,2})[-/.]'))
        let year := extractRegex(value, '([0-9]{4})\$')
        return isValidDate(year, month, day) ? concat(year, month, day) : ''
    }
    return ''
}

// Meta matches a hash only when it normalized the raw value the same way before hashing it. A value
// that cannot match after normalization is dropped rather than hashed. The rules per field:
// https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters
fn normalizeUserValue(key, value) {
    let normalized := lower(trimSpace(value))
    if (key == 'em') {
        return match(normalized, '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+\$') ? normalized : ''
    } else if (key == 'ph') {
        // Digits only, country code included, no leading zeros, at most 15 digits as in E.164
        let digits := trimLeft(keepMatching(normalized, '^[0-9]\$'), '0')
        return match(digits, '^[1-9][0-9]{6,14}\$') ? digits : ''
    } else if (key == 'fn' or key == 'ln' or key == 'ct') {
        return keepMatching(normalized, '^[\\\\p{L}\\\\p{M}]\$')
    } else if (key == 'st') {
        return keepMatching(normalized, '^[\\\\p{L}\\\\p{N}]\$')
    } else if (key == 'zp') {
        let postal := keepMatching(normalized, '^[\\\\p{L}\\\\p{N}]\$')
        let countryGiven := not empty(parseValueIfArray(inputs.userData.country))
        if (isUnitedStates(inputs.userData.country) or (not countryGiven and match(normalized, '^[0-9]{5}-[0-9]{4}\$'))) {
            // Meta takes only the first 5 digits of a US ZIP+4 code
            if (match(postal, '^[0-9]{9}\$')) {
                return substring(postal, 1, 5)
            }
            return match(postal, '^[0-9]{5}\$') ? postal : ''
        }
        return postal
    } else if (key == 'country') {
        return normalizeCountry(normalized)
    } else if (key == 'db') {
        return normalizeDateOfBirth(normalized)
    } else if (key == 'ge') {
        if (normalized == 'f' or normalized == 'female') {
            return 'f'
        } else if (normalized == 'm' or normalized == 'male') {
            return 'm'
        }
        return ''
    }
    return normalized
}

// Meta's own ParamBuilder libraries hash a value into <64-character digest>[.<appendix>], the
// same optional-appendix shape freshClickId above already expects from a ParamBuilder-stamped
// fbc. The digest is case-insensitive; the appendix is not, so only the digest is lowercased.
// A value in this shape is sent through unchanged instead of being hashed again.
fn preHashedValue(value) {
    let trimmed := trimSpace(value)
    if (not match(trimmed, '^[A-Fa-f0-9]{64}([.][A-Za-z0-9_-]+)?\$')) {
        return null
    }
    let digest := lower(substring(trimmed, 1, 64))
    let tailLength := length(trimmed) - 64
    return tailLength > 0 ? concat(digest, substring(trimmed, 65, tailLength)) : digest
}

fn hashUserValue(key, value) {
    if (empty(value)) {
        return null
    }
    let preHashed := preHashedValue(value)
    if (preHashed != null) {
        return preHashed
    }
    let normalized := normalizeUserValue(key, value)
    return empty(normalized) ? null : sha256Hex(normalized)
}

fn hashUserData(key, value) {
    let parsed := parseValueIfArray(value)
    if (typeof(parsed) != 'array') {
        return hashUserValue(key, parsed)
    }
    let hashes := []
    let itemCount := length(parsed) > MAX_USER_DATA_LIST_LENGTH ? MAX_USER_DATA_LIST_LENGTH : length(parsed)
    for (let i := 1; i <= itemCount; i := i + 1) {
        let hashed := hashUserValue(key, parsed[i])
        if (not empty(hashed)) {
            hashes := arrayPushBack(hashes, hashed)
        }
    }
    return hashes
}

for (let key, value in inputs.userData) {
    let cleaned := null
    if (key == 'fbc') {
        cleaned := newestClickId(value)
    } else if (key == 'fbp') {
        cleaned := firstBrowserId(value)
    } else if (has(HASHED_USER_KEYS, key)) {
        cleaned := hashUserData(key, value)
    } else {
        cleaned := parseValueIfArray(value)
    }
    if (not empty(cleaned)) {
        body.data.1.user_data[key] := cleaned
    }
}

// Meta rejects an event without customer information (error 2804050), so it is skipped instead.
if (empty(body.data.1.user_data)) {
    print('No customer information left after normalization. Skipping...')
    return
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
                'A map that contains customer information data. Send raw values for em, ph, fn, ln, ge, db, ct, st, zp, and country: they are normalized and hashed before sending, and a value that is already a SHA-256 hash is sent as is. See this page for options: https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters',
            default: {
                em: '{person.properties.email}',
                ph: '{person.properties.phone}',
                fn: '{person.properties.first_name}',
                ln: '{person.properties.last_name}',
                ct: '{person.properties.$geoip_city_name}',
                st: '{person.properties.$geoip_subdivision_1_code}',
                zp: '{person.properties.$geoip_postal_code}',
                country: '{person.properties.$geoip_country_code}',
                fbc,
                fbp,
                client_ip_address: '{event.properties.$ip}',
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

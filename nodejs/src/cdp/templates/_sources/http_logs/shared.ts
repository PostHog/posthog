import { HogFunctionInputSchemaType } from '~/cdp/types'

// Shared implementation for $http_log source webhooks (generic HTTP server logs and
// Cloudflare logs). Accepts exactly one JSON log record per request and emits one
// $http_log event — source webhooks can only capture a single event per invocation,
// so senders must post records individually rather than in batches.
//
// Record contract:
//   url          full request URL (or send host/path/scheme separately)
//   host         request host — overrides the host parsed from url
//   path         request path with query string — used when url is absent
//   scheme       http/https — used when url has no scheme (default https)
//   method       HTTP method
//   status_code  response status code
//   ip           client IP
//   user_agent   client user agent (required for bot detection)
//   referrer     Referer header
//   timestamp    epoch milliseconds of the request (optional)
//   properties   object of extra event properties, passed through
export const HTTP_LOG_SOURCE_HOG_CODE = `
if (inputs.debug) {
    print('Incoming headers:', request.headers)
    print('Incoming body:', request.body)
}

if (request.method != 'POST') {
    return {
        'httpResponse': {
            'status': 405,
            'body': 'Method not allowed'
        }
    }
}

if (notEmpty(inputs.auth_header) and inputs.auth_header != request.headers['authorization']) {
    print('Denied: bad Authorization header')
    return {
        'httpResponse': {
            'status': 401,
            'body': 'Unauthorized'
        }
    }
}

let record := request.body
if (typeof(record) != 'object' and typeof(record) != 'array' and notEmpty(request.stringBody)) {
    record := jsonParse(request.stringBody)
}

if (typeof(record) == 'array') {
    return {
        'httpResponse': {
            'status': 400,
            'body': {
                'error': 'Send one log record per request. One request emits one $http_log event, and batched arrays are not supported.'
            }
        }
    }
}

if (typeof(record) != 'object') {
    return {
        'httpResponse': {
            'status': 400,
            'body': {
                'error': 'Expected a JSON object describing one HTTP request'
            }
        }
    }
}

// Resolve scheme, host, and path-with-query from either a full "url" or separate fields.
let scheme := record.scheme ?? 'https'
let host := record.host ?? ''
let pathWithQuery := record.path ?? ''
let url := record.url ?? ''

if (notEmpty(url) and typeof(url) == 'string') {
    let rest := url
    let schemeIdx := position(url, '://')
    if (schemeIdx > 0) {
        scheme := substring(url, 1, schemeIdx - 1)
        rest := substring(url, schemeIdx + 3, length(url) - schemeIdx - 2)
    }
    let slashIdx := position(rest, '/')
    if (slashIdx > 0) {
        if (empty(host)) {
            host := substring(rest, 1, slashIdx - 1)
        }
        if (empty(pathWithQuery)) {
            pathWithQuery := substring(rest, slashIdx, length(rest) - slashIdx + 1)
        }
    } else if (empty(host)) {
        host := rest
    }
}

if (empty(host)) {
    return {
        'httpResponse': {
            'status': 400,
            'body': {
                'error': 'Missing "url" (or "host") on the log record'
            }
        }
    }
}

if (empty(pathWithQuery)) {
    pathWithQuery := '/'
} else if (substring(pathWithQuery, 1, 1) != '/') {
    pathWithQuery := f'/{pathWithQuery}'
}

fun parseQueryParams(u) {
    if (empty(u) or typeof(u) != 'string') {
        return {}
    }
    let queryIndex := position(u, '?')
    if (queryIndex == 0) {
        return {}
    }
    let queryString := substring(u, queryIndex + 1, length(u) - queryIndex)
    if (empty(queryString)) {
        return {}
    }
    let params := {}
    let pairs := splitByString('&', queryString)
    for (let _, pair in pairs) {
        if (empty(pair)) {
            continue
        }
        // Split on the first '=' only, so values containing '=' (base64, signed tokens) survive.
        let eqIdx := position(pair, '=')
        if (eqIdx > 0) {
            let key := substring(pair, 1, eqIdx - 1)
            let value := substring(pair, eqIdx + 1, length(pair) - eqIdx)
            if (notEmpty(key) and notEmpty(value)) {
                params[key] := tryDecodeURLComponent(value) ?? value
            }
        }
    }
    return params
}

fun extractPathname(u) {
    if (empty(u) or typeof(u) != 'string') {
        return ''
    }
    let queryIndex := position(u, '?')
    if (queryIndex > 0) {
        return substring(u, 1, queryIndex - 1)
    }
    return u
}

// Extension of the last path segment, lowercased; '' when there is none.
fun pathExtension(p) {
    if (empty(p) or typeof(p) != 'string') {
        return ''
    }
    let segments := splitByString('/', p)
    let lastSegment := segments[length(segments)]
    if (empty(lastSegment)) {
        return ''
    }
    let parts := splitByString('.', lastSegment)
    if (length(parts) <= 1) {
        return ''
    }
    return lower(parts[length(parts)])
}

// Top-level document request: a path with no file extension (e.g. /pricing,
// /docs/x) or an HTML document. Everything else is a sub-resource (JS, CSS,
// image, font, JSON, source map).
fun isPageRoute(p) {
    let ext := pathExtension(p)
    return ext == '' or ext == 'html' or ext == 'htm'
}

let pathname := extractPathname(pathWithQuery)

if (inputs.page_routes_only and not isPageRoute(pathname)) {
    // Not a page route — ack with 200 so the sender does not retry.
    return {
        'httpResponse': {
            'status': 200,
            'body': 'OK'
        }
    }
}

let clientIp := record.ip ?? ''
let userAgent := record.user_agent ?? ''

// Distinct ID: configurable strategy. Default is a fixed salted hash of (ip, host, ua) —
// one stable ID per client. The active strategy is recorded as $distinct_id_strategy
// on the event for diagnostics — it is not an analytical breakdown dimension.
let day := formatDateTime(now(), '%Y-%m-%d')
let salt := inputs.salt_secret ?? ''
let strategy := inputs.distinct_id_strategy ?? 'fixed_salt'
let activeStrategy := strategy
let distinctId := ''

// Hashed strategies emit a 22-char unpadded base64 prefix of sha256, matching
// the visual format of PostHog cookieless distinct IDs (132 bits of entropy —
// far more than needed for collision resistance, and short enough to be readable).
fun shortHash(input) {
    return substring(sha256(input, 'base64'), 1, 22)
}

if (strategy == 'rotating_salt') {
    distinctId := f'http_log_{shortHash(f'{salt}:{day}:{clientIp}:{host}:{userAgent}')}'
} else if (strategy == 'fixed_salt') {
    distinctId := f'http_log_{shortHash(f'{salt}:{clientIp}:{host}:{userAgent}')}'
} else if (strategy == 'ip') {
    distinctId := f'http_log_{clientIp}'
} else if (strategy == 'custom') {
    let customTemplate := inputs.custom_template ?? ''
    if (empty(customTemplate)) {
        print('http log source: custom_template empty, falling back to rotating_salt')
        distinctId := f'http_log_{shortHash(f'{salt}:{day}:{clientIp}:{host}:{userAgent}')}'
        activeStrategy := 'rotating_salt_fallback'
    } else {
        let result := customTemplate
        // Note: {salt} is intentionally NOT a placeholder — exposing the secret
        // in distinct_ids would defeat its purpose (events are stored in plain text).
        result := replaceAll(result, '{day}', day)
        result := replaceAll(result, '{ip}', clientIp)
        result := replaceAll(result, '{host}', host)
        result := replaceAll(result, '{ua}', userAgent)
        result := replaceAll(result, '{path}', pathname)
        // Guard: if every placeholder resolved to empty, fall back to rotating_salt
        // so we don't collapse all such requests onto a single 'http_log_' id.
        if (empty(result)) {
            print('http log source: custom_template substituted to empty, falling back to rotating_salt')
            distinctId := f'http_log_{shortHash(f'{salt}:{day}:{clientIp}:{host}:{userAgent}')}'
            activeStrategy := 'rotating_salt_fallback'
        } else {
            distinctId := f'http_log_{result}'
        }
    }
} else {
    // Unknown strategy value — treat as rotating_salt
    distinctId := f'http_log_{shortHash(f'{salt}:{day}:{clientIp}:{host}:{userAgent}')}'
    activeStrategy := 'rotating_salt'
}

let queryParams := parseQueryParams(pathWithQuery)

let props := {}

// Passthrough properties first, so the standard fields below always win.
let extra := record.properties
if (typeof(extra) == 'object') {
    for (let key in keys(extra)) {
        props[key] := extra[key]
    }
}

// Person processing. Anonymous by default ($process_person_profile = false) so high-cardinality
// log traffic does not create a person profile per distinct ID — cheaper and faster to query.
// Set the "Person processing" input to "identified" to create person profiles for stitching.
props['$process_person_profile'] := inputs.person_processing == 'identified'
props['$distinct_id_strategy'] := activeStrategy
props['$current_url'] := f'{scheme}://{host}{pathWithQuery}'
props['$host'] := host
props['$pathname'] := pathname

if (notEmpty(record.referrer ?? record.referer)) {
    props['$referrer'] := record.referrer ?? record.referer
}
if (notEmpty(record.method)) {
    props['method'] := record.method
}
if (record.status_code != null) {
    props['status_code'] := record.status_code
}
if (record.timestamp != null) {
    props['log_timestamp_ms'] := record.timestamp
}

// UTM parameters (extracted from URL query string)
if (notEmpty(queryParams['utm_source'])) {
    props['utm_source'] := queryParams['utm_source']
}
if (notEmpty(queryParams['utm_medium'])) {
    props['utm_medium'] := queryParams['utm_medium']
}
if (notEmpty(queryParams['utm_campaign'])) {
    props['utm_campaign'] := queryParams['utm_campaign']
}
if (notEmpty(queryParams['utm_term'])) {
    props['utm_term'] := queryParams['utm_term']
}
if (notEmpty(queryParams['utm_content'])) {
    props['utm_content'] := queryParams['utm_content']
}

// $ip and $raw_user_agent are gated so raw client identifiers can be kept off the
// emitted event. On by default, since PostHog's GeoIP and UA (bot) enrichment depend on them.
if (inputs.forward_ip_and_user_agent) {
    props['$ip'] := clientIp
    props['$raw_user_agent'] := userAgent
}

postHogCapture({
    'event': '$http_log',
    'distinct_id': distinctId,
    'properties': props
})

return {
    'httpResponse': {
        'status': 200,
        'body': 'OK'
    }
}
`

// Inputs shared by every $http_log source template. `authHeaderDescription` lets a
// template attach provider-specific setup instructions (rendered as markdown) to the
// secret the sender must present.
export function httpLogSourceInputsSchema(options: { authHeaderDescription: string }): HogFunctionInputSchemaType[] {
    return [
        {
            key: 'auth_header',
            type: 'string',
            label: 'Authorization header value',
            description: options.authHeaderDescription,
            secret: true,
            required: false,
        },
        {
            key: 'page_routes_only',
            type: 'boolean',
            label: 'Only capture page routes',
            description:
                'When enabled, only top-level document requests are captured: paths with no file extension (e.g. /pricing, /docs/x) or ending in .html/.htm. Sub-resource requests (JS, CSS, images, fonts, JSON, source maps) are skipped and acknowledged with 200 so the sender does not retry them. A single page view fans out into many sub-resource requests, so this keeps $http_log close to a document/pageview stream and cuts ingested volume substantially. Off by default, so the full HTTP access log is captured. Note: extension-less API routes (e.g. /api/x) are also kept.',
            secret: false,
            required: false,
            default: false,
        },
        {
            key: 'salt_secret',
            type: 'string',
            label: 'Distinct ID salt',
            description:
                'High-entropy random secret (e.g. base64) mixed into hashed distinct IDs. Rotate to invalidate prior IDs. Used by rotating_salt, fixed_salt, and the rotating_salt_fallback path of custom; ignored by the ip strategy. If left blank, hashed strategies still produce stable IDs but lose the unguessability the salt provides. Set one in production.',
            secret: true,
            required: false,
        },
        {
            key: 'distinct_id_strategy',
            type: 'choice',
            label: 'Distinct ID strategy',
            description:
                'How distinct IDs are derived from the request. Because events are anonymous by default (no person profiles), this affects unique-visitor counting rather than cost. The default, fixed salt, gives one stable ID per client (IP + host + user agent) for accurate uniques. Rotating salt rotates that ID daily for extra privacy, at the cost of inflated unique counts. The active strategy is recorded on each event as $distinct_id_strategy for debugging.',
            choices: [
                {
                    value: 'fixed_salt',
                    label: 'Fixed salt (sha256(salt:ip:host:ua)): one stable ID per client, default',
                },
                {
                    value: 'rotating_salt',
                    label: 'Rotating salt (sha256(salt:day:ip:host:ua)): rotates daily for privacy',
                },
                {
                    value: 'ip',
                    label: 'Raw IP: stores client IPs unhashed as queryable distinct IDs',
                },
                {
                    value: 'custom',
                    label: 'Custom template: placeholder substitution (see template field)',
                },
            ],
            default: 'fixed_salt',
            secret: false,
            required: true,
        },
        {
            key: 'person_processing',
            type: 'choice',
            label: 'Person processing',
            description:
                'Whether each event creates a person profile. "Anonymous" (default) emits $process_person_profile=false so high-cardinality log traffic does not create a person profile per distinct ID. Cheaper, faster to query, and recommended for aggregate traffic and bot analysis. "Identified" creates a person profile per distinct ID for person-level stitching (billed on the person-profiles line).',
            choices: [
                {
                    value: 'anonymous',
                    label: 'Anonymous: no person profiles (recommended for log traffic)',
                },
                {
                    value: 'identified',
                    label: 'Identified: create a person profile per distinct ID',
                },
            ],
            default: 'anonymous',
            secret: false,
            required: true,
        },
        {
            key: 'forward_ip_and_user_agent',
            type: 'boolean',
            label: 'Forward client IP and user agent',
            description:
                'When enabled (default), $ip and $raw_user_agent are emitted on each event so PostHog can run GeoIP, user-agent, and bot enrichment. Disable if you want raw client identifiers stripped: distinct_id derivation still uses them as inputs, but they will not appear on the emitted event.',
            secret: false,
            required: false,
            default: true,
        },
        {
            key: 'custom_template',
            type: 'string',
            label: 'Custom distinct ID template',
            description:
                'Used only when strategy is "custom". Supports placeholders {day}, {ip}, {host}, {ua}, {path} (literal string substitution, not Hog evaluation; unknown placeholders are left as-is). The salt secret is intentionally not exposed as a placeholder. The result is prefixed with "http_log_". Empty value or all-empty substitutions fall back to rotating_salt.',
            secret: false,
            required: false,
            // Templating disabled so {placeholder} braces are not interpreted as Hog
            // expressions at the input layer. Substitution happens inside the Hog code.
            templating: false,
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log payloads',
            description: 'Logs the incoming request for debugging',
            secret: false,
            required: false,
            default: false,
        },
    ]
}

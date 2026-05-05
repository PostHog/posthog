import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'source_webhook',
    id: 'template-source-vercel-log-drain',
    name: 'Vercel logs',
    description: 'Capture Vercel deployment logs as PostHog events',
    icon_url: '/static/services/webhook.svg',
    category: ['Infrastructure', 'Monitoring'],
    code_language: 'hog',
    code: `
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

let logs := []
let body := request.stringBody ?? ''

fun isValidLog(obj) {
    return typeof(obj) == 'object' and notEmpty(obj.id) and notEmpty(obj.deploymentId)
}

fun pushLog(obj) {
    if (not isValidLog(obj)) {
        return
    }
    logs := arrayPushBack(logs, obj)
}

fun pushParsed(parsed) {
    if (typeof(parsed) == 'array') {
        for (let _, item in parsed) {
            pushLog(item)
        }
    } else if (typeof(parsed) == 'object') {
        pushLog(parsed)
    }
}

// Check if body contains newlines (NDJSON format)
let hasNewlines := position(body, '\\n') > 0

if (hasNewlines) {
    // Parse as NDJSON (newline-delimited JSON)
    let lines := splitByString('\\n', body)
    for (let _, line in lines) {
        let s := trim(line)
        if (empty(s)) {
            continue
        }
        let obj := jsonParse(s)
        pushLog(obj)
    }
} else if (notEmpty(body)) {
    pushParsed(jsonParse(body))
}

// Fallback: if stringBody was empty but the parsed body is available, use it directly.
// This handles cases where the webhook infrastructure consumed the raw body for JSON parsing.
if (empty(logs) and notEmpty(request.body)) {
    pushParsed(request.body)
}

if (empty(logs)) {
    return {
        'httpResponse': {
            'status': 400,
            'body': {
                'error': 'No valid Vercel log objects found'
            }
        }
    }
}

// Technical limitation: Hog functions can only call postHogCapture once per invocation.
// If Vercel batches multiple logs in one request, we capture only the first one.
// Configure Vercel to send logs individually for complete coverage.
let droppedCount := length(logs) - 1
if (droppedCount > 0) {
    print(f'Warning: Dropped {droppedCount} additional log(s). Hog functions can only emit one event per invocation.')
}

let log := logs[1]
let proxy := log.proxy ?? {}

let limit := toInt(inputs.max_message_len ?? 262144)

fun truncateIfNeeded(s) {
    if (typeof(s) != 'string') {
        return s
    }
    if (length(s) <= limit) {
        return s
    }
    return substring(s, 1, limit)
}

fun parseQueryParams(url) {
    if (empty(url) or typeof(url) != 'string') {
        return {}
    }
    let queryIndex := position(url, '?')
    if (queryIndex == 0) {
        return {}
    }
    let queryString := substring(url, queryIndex + 1, length(url) - queryIndex)
    if (empty(queryString)) {
        return {}
    }
    let params := {}
    let pairs := splitByString('&', queryString)
    for (let _, pair in pairs) {
        if (empty(pair)) {
            continue
        }
        let kv := splitByString('=', pair, 2)
        let key := kv[1]
        if (length(kv) > 1 and notEmpty(kv[2])) {
            params[key] := tryDecodeURLComponent(kv[2]) ?? kv[2]
        }
    }
    return params
}

fun extractPathname(url) {
    if (empty(url) or typeof(url) != 'string') {
        return ''
    }
    let queryIndex := position(url, '?')
    if (queryIndex > 0) {
        return substring(url, 1, queryIndex - 1)
    }
    return url
}

// Distinct ID: configurable strategy. Default is a daily-rotating salted hash
// of (ip, host, ua). The active strategy is recorded as $distinct_id_strategy
// on the event for diagnostics — it is not an analytical breakdown dimension.
let host := proxy.host ?? log.host ?? ''
let clientIp := proxy.clientIp ?? ''
let userAgent := proxy.userAgent[1] ?? ''
let scheme := proxy.scheme ?? 'https'
let path := proxy.path ?? log.path ?? ''

let day := formatDateTime(now(), '%Y-%m-%d')
let salt := inputs.salt_secret ?? ''
let strategy := inputs.distinct_id_strategy ?? 'rotating_salt'
let activeStrategy := strategy
let distinctId := ''

if (strategy == 'rotating_salt') {
    distinctId := f'http_log_{sha256Hex(f'{salt}:{day}:{clientIp}:{host}:{userAgent}')}'
} else if (strategy == 'fixed_salt') {
    distinctId := f'http_log_{sha256Hex(f'{salt}:{clientIp}:{host}:{userAgent}')}'
} else if (strategy == 'ip') {
    distinctId := f'http_log_{clientIp}'
} else if (strategy == 'custom') {
    let customTemplate := inputs.custom_template ?? ''
    if (empty(customTemplate)) {
        print('vercel log drain: custom_template empty, falling back to rotating_salt')
        distinctId := f'http_log_{sha256Hex(f'{salt}:{day}:{clientIp}:{host}:{userAgent}')}'
        activeStrategy := 'rotating_salt_fallback'
    } else {
        let result := customTemplate
        result := replaceAll(result, '{salt}', salt)
        result := replaceAll(result, '{day}', day)
        result := replaceAll(result, '{ip}', clientIp)
        result := replaceAll(result, '{host}', host)
        result := replaceAll(result, '{ua}', userAgent)
        result := replaceAll(result, '{path}', path)
        result := replaceAll(result, '{project_id}', toString(log.projectId))
        distinctId := f'http_log_{result}'
    }
} else {
    // Unknown strategy value — treat as rotating_salt
    distinctId := f'http_log_{sha256Hex(f'{salt}:{day}:{clientIp}:{host}:{userAgent}')}'
    activeStrategy := 'rotating_salt'
}

// Parse URL for pathname and UTM parameters
let queryParams := parseQueryParams(path)
let pathname := extractPathname(path)

let props := {
    // PostHog standard properties. $ip and $raw_user_agent are added below
    // when forward_ip_and_user_agent is enabled — defaults to off so the
    // strategy hashing isn't undermined by raw PII landing on every event.
    '$distinct_id_strategy': activeStrategy,
    '$current_url': f'{scheme}://{host}{path}',
    '$host': host,
    '$pathname': pathname,
    '$referrer': proxy.referer,

    // UTM parameters (extracted from URL query string)
    'utm_source': queryParams['utm_source'],
    'utm_medium': queryParams['utm_medium'],
    'utm_campaign': queryParams['utm_campaign'],
    'utm_term': queryParams['utm_term'],
    'utm_content': queryParams['utm_content'],

    // Core log fields
    'vercel_log_id': log.id,
    'deployment_id': log.deploymentId,
    'project_id': log.projectId,
    'project_name': log.projectName,
    'source': log.source,
    'environment': log.environment,
    'level': log.level,
    'type': log.type,
    'message': truncateIfNeeded(log.message),
    'message_truncated': typeof(log.message) == 'string' and length(log.message ?? '') > limit,
    'vercel_timestamp_ms': log.timestamp,

    // Request info
    'host': log.host,
    'path': log.path,
    'entrypoint': log.entrypoint,
    'status_code': log.statusCode,
    'request_id': log.requestId,
    'execution_region': log.executionRegion,
    'invocation_id': log.invocationId,
    'instance_id': log.instanceId,

    // Build/deploy info
    'build_id': log.buildId,
    'branch': log.branch,
    'destination': log.destination,

    // Edge/middleware
    'edge_type': log.edgeType,

    // Tracing
    'trace_id': log.traceId ?? log['trace.id'],
    'span_id': log.spanId ?? log['span.id'],

    // Security fingerprints
    'ja3_digest': log.ja3Digest,
    'ja4_digest': log.ja4Digest,

    // Proxy fields (flattened)
    'proxy_timestamp_ms': proxy.timestamp,
    'proxy_method': proxy.method,
    'proxy_host': proxy.host,
    'proxy_path': proxy.path,
    'proxy_user_agent': proxy.userAgent,
    'proxy_region': proxy.region,
    'proxy_referer': proxy.referer,
    'proxy_status_code': proxy.statusCode,
    'proxy_client_ip': proxy.clientIp,
    'proxy_scheme': proxy.scheme,
    'proxy_response_byte_size': proxy.responseByteSize,
    'proxy_cache_id': proxy.cacheId,
    'proxy_path_type': proxy.pathType,
    'proxy_path_type_variant': proxy.pathTypeVariant,
    'proxy_vercel_id': proxy.vercelId,
    'proxy_vercel_cache': proxy.vercelCache,
    'proxy_lambda_region': proxy.lambdaRegion,
    'proxy_waf_action': proxy.wafAction,
    'proxy_waf_rule_id': proxy.wafRuleId
}

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
`,

    inputs_schema: [
        {
            key: 'auth_header',
            type: 'string',
            label: 'Authorization header value',
            description:
                'If set, the incoming Authorization header must match this value exactly. e.g. "Bearer SECRET_TOKEN"',
            secret: true,
            required: false,
        },
        {
            key: 'max_message_len',
            type: 'number',
            label: 'Max message length',
            description: 'Truncate log messages longer than this (default: 262144 bytes)',
            default: 262144,
            secret: false,
            required: false,
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
        {
            key: 'salt_secret',
            type: 'string',
            label: 'Distinct ID salt',
            description:
                'High-entropy random secret (e.g. base64) mixed into hashed distinct IDs. Rotate to invalidate prior IDs. Required by all strategies except "ip".',
            secret: true,
            required: true,
        },
        {
            key: 'distinct_id_strategy',
            type: 'choice',
            label: 'Distinct ID strategy',
            description:
                'How distinct IDs are derived. Default rotates daily so the same client gets a fresh ID each day. The active strategy is recorded on each event as $distinct_id_strategy for debugging.',
            choices: [
                {
                    value: 'rotating_salt',
                    label: 'Rotating salt (sha256(salt:day:ip:host:ua)) — daily rotation, default',
                },
                {
                    value: 'fixed_salt',
                    label: 'Fixed salt (sha256(salt:ip:host:ua)) — stable until salt rotates',
                },
                {
                    value: 'ip',
                    label: 'Raw IP — stores client IPs unhashed as queryable distinct IDs',
                },
                {
                    value: 'custom',
                    label: 'Custom template — placeholder substitution (see template field)',
                },
            ],
            default: 'rotating_salt',
            secret: false,
            required: true,
        },
        {
            key: 'forward_ip_and_user_agent',
            type: 'boolean',
            label: 'Forward client IP and user agent',
            description:
                'When enabled, $ip and $raw_user_agent are emitted on every event (PostHog uses $ip for GeoIP enrichment). Off by default so raw PII does not land on events alongside hashed distinct IDs. Safe to enable when distinct_id_strategy is "ip", or whenever you do not need the strategy hashing to obscure the client.',
            secret: false,
            required: false,
            default: false,
        },
        {
            key: 'custom_template',
            type: 'string',
            label: 'Custom distinct ID template',
            description:
                'Used only when strategy is "custom". Supports placeholders {salt}, {day}, {ip}, {host}, {ua}, {path}, {project_id} (literal string substitution, not Hog evaluation; unknown placeholders are left as-is). The result is prefixed with "http_log_". Empty value falls back to rotating_salt.',
            secret: false,
            required: false,
            // Templating disabled so {placeholder} braces are not interpreted as Hog
            // expressions at the input layer. Substitution happens inside the Hog code.
            templating: false,
        },
    ],
}

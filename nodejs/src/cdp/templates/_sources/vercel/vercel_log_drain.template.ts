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

// Distinct ID: user-level grouping based on project, host, client IP, and user agent
let host := proxy.host ?? log.host ?? ''
let clientIp := proxy.clientIp ?? ''
let userAgent := proxy.userAgent[1] ?? ''
let scheme := proxy.scheme ?? 'https'
let path := proxy.path ?? log.path ?? ''
let distinctId := f'vercel_{sha256Hex(f'{log.projectId}:{host}:{clientIp}:{userAgent}')}'

let props := {
    // PostHog standard properties
    '$ip': clientIp,
    '$raw_user_agent': userAgent,
    '$current_url': f'{scheme}://{host}{path}',

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
    ],
}

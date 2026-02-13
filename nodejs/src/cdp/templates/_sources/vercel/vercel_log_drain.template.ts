import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'source_webhook',
    id: 'template-source-vercel-log-drain',
    name: 'Vercel log drain',
    description: 'Capture Vercel deployment logs as events',
    icon_url: '/static/services/vercel.png',
    category: ['Infrastructure', 'Monitoring'],
    code_language: 'hog',
    code: `
if (inputs.debug) {
    print('Incoming headers:', request.headers)
    print('Incoming raw body (first 1k):', substring(request.stringBody, 0, 1000))
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

fun isAllowedSource(source) {
    if (empty(inputs.allowed_sources)) {
        return true
    }
    for (let _, allowed in inputs.allowed_sources) {
        if (source == allowed) {
            return true
        }
    }
    return false
}

fun pushLog(obj) {
    if (not isValidLog(obj)) {
        return
    }
    if (not isAllowedSource(obj.source)) {
        return
    }
    logs := arrayPushBack(logs, obj)
}

// Check if body contains newlines (NDJSON format)
let hasNewlines := position(body, '\n') > 0

if (hasNewlines) {
    // Parse as NDJSON (newline-delimited JSON)
    let lines := splitByString('\n', body)
    for (let _, line in lines) {
        let s := trim(line)
        if (empty(s)) {
            continue
        }
        let obj := jsonParse(s)
        pushLog(obj)
    }
} else if (notEmpty(body)) {
    // Parse as single JSON object or array
    let parsed := jsonParse(body)
    if (typeof(parsed) == 'array') {
        for (let _, item in parsed) {
            pushLog(item)
        }
    } else if (typeof(parsed) == 'object') {
        pushLog(parsed)
    }
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

// Use first log for distinct_id (deploymentId:requestId)
let firstLog := logs[1]
let distinctId := concat(
    firstLog.deploymentId ?? 'dpl_unknown',
    ':',
    firstLog.requestId ?? firstLog.id ?? 'log'
)

// Build array of log entries
let logEntries := []
for (let _, log in logs) {
    let entry := {
        'id': log.id,
        'deploymentId': log.deploymentId,
        'projectId': log.projectId,
        'projectName': log.projectName,
        'source': log.source,
        'environment': log.environment,
        'host': log.host,
        'path': log.path,
        'entrypoint': log.entrypoint,
        'type': log.type,
        'level': log.level,
        'statusCode': log.statusCode,
        'requestId': log.requestId,
        'executionRegion': log.executionRegion,
        'edgeType': log.edgeType,
        'traceId': log.traceId ?? log['trace.id'],
        'spanId': log.spanId ?? log['span.id'],
        'vercel_timestamp_ms': log.timestamp,
        'message': truncateIfNeeded(log.message),
        'message_truncated': typeof(log.message) == 'string' and length(log.message) > limit,
        'buildId': log.buildId,
        'destination': log.destination,
        'branch': log.branch,
        'ja3Digest': log.ja3Digest,
        'ja4Digest': log.ja4Digest,
        'proxy': log.proxy
    }
    logEntries := arrayPushBack(logEntries, entry)
}

let props := {
    'log_count': length(logEntries),
    'logs': logEntries,
    'first_log': logEntries[1]
}

postHogCapture({
    'event': '$log_http_hit',
    'distinct_id': distinctId,
    'properties': props
})

return {
    'httpResponse': {
        'status': 200,
        'body': f'Captured {length(logEntries)} Vercel log events'
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
            key: 'allowed_sources',
            type: 'choice',
            label: 'Allowed sources',
            description: 'Only capture logs from these sources. Leave empty to capture all.',
            choices: [
                { label: 'Build', value: 'build' },
                { label: 'Edge', value: 'edge' },
                { label: 'Lambda', value: 'lambda' },
                { label: 'Static', value: 'static' },
                { label: 'External', value: 'external' },
                { label: 'Firewall', value: 'firewall' },
                { label: 'Redirect', value: 'redirect' },
            ],
            default: '',
            secret: false,
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

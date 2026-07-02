import type { LogRecord } from '../../log-record-avro'

// Fixtures for benchmarking Hog programs against realistic log records.
// Record sizes are calibrated to the production average of ~0.9KB uncompressed per record.

export interface BenchProgram {
    id: string
    name: string
    hog: string
    inputs: Record<string, unknown>
}

export interface BenchGlobals {
    project: { id: number; name: string; url: string }
    record: Record<string, unknown>
    inputs: Record<string, unknown>
}

const NOW_NS = 1_780_000_000_000_000_000

export const BENCH_LOG_RECORDS: { id: string; record: LogRecord }[] = [
    {
        id: 'plain-body',
        record: {
            uuid: '0197a3f2-1111-7000-8000-000000000001',
            trace_id: null,
            span_id: null,
            trace_flags: 0,
            timestamp: NOW_NS,
            observed_timestamp: NOW_NS,
            // sk_fake_ prefix: shaped like a payment-provider secret for the scrub benchmark
            // without tripping GitHub push protection on a real-looking key.
            body: 'Failed to authorize request for user jane.doe@example.com with token Bearer sk_fake_abcdef1234567890abcdef1234567890 — retrying with backoff. Previous attempt failed after 1523ms due to upstream timeout from payments-gateway. Contact ops@example.com if this persists across more than three consecutive attempts.',
            severity_text: 'error',
            severity_number: 17,
            service_name: 'payments-api',
            resource_attributes: {
                'k8s.namespace.name': 'payments',
                'k8s.pod.name': 'payments-api-6d8f9c7b4-x2j9q',
                'deployment.environment': 'production',
                'cloud.region': 'us-east-1',
            },
            instrumentation_scope: 'payments.auth',
            event_name: null,
            attributes: {
                'http.method': 'POST',
                'http.status_code': '401',
                'http.route': '/api/v1/charges',
                'user.email': 'jane.doe@example.com',
                retry_count: '3',
                duration_ms: '1523',
                distinct_id: 'user_8f3k2j1h',
            },
            bytes_uncompressed: 880,
        },
    },
    {
        id: 'json-body',
        record: {
            uuid: '0197a3f2-1111-7000-8000-000000000002',
            trace_id: null,
            span_id: null,
            trace_flags: 0,
            timestamp: NOW_NS,
            observed_timestamp: NOW_NS,
            body: JSON.stringify({
                level: 'info',
                msg: 'order processed',
                order_id: 'ord_29f8a3kd02',
                customer: { id: 'cus_8d3f2', email: 'buyer@example.org', country: 'DE' },
                items: [
                    { sku: 'SKU-1001', qty: 2, price_cents: 1999 },
                    { sku: 'SKU-2044', qty: 1, price_cents: 5499 },
                ],
                payment: { provider: 'stripe', token: 'sk_fake_51JxYzabcdef1234567890abcdef12', status: 'captured' },
                latency_ms: 187,
                attempt: 1,
            }),
            severity_text: 'info',
            severity_number: 9,
            service_name: 'orders-worker',
            resource_attributes: {
                'k8s.namespace.name': 'commerce',
                'k8s.pod.name': 'orders-worker-7f6d5c4b3-a1b2c',
                'deployment.environment': 'production',
            },
            instrumentation_scope: 'orders.processor',
            event_name: null,
            attributes: {
                'queue.name': 'orders-high',
                'messaging.operation': 'process',
                distinct_id: 'user_2k4j5h6g',
            },
            bytes_uncompressed: 920,
        },
    },
    {
        id: 'fat-attributes',
        record: {
            uuid: '0197a3f2-1111-7000-8000-000000000003',
            trace_id: null,
            span_id: null,
            trace_flags: 0,
            timestamp: NOW_NS,
            observed_timestamp: NOW_NS,
            body: 'request completed',
            severity_text: 'debug',
            severity_number: 5,
            service_name: 'edge-router',
            resource_attributes: {
                'k8s.namespace.name': 'edge',
                'k8s.pod.name': 'edge-router-5c4b3a2d1-q9w8e',
                'deployment.environment': 'production',
                'cloud.region': 'eu-west-1',
                'host.name': 'ip-10-0-12-34',
            },
            instrumentation_scope: 'edge.http',
            event_name: null,
            attributes: Object.fromEntries(
                Array.from({ length: 30 }, (_, i) => [`dim.field_${i}`, `value-${i}-${'x'.repeat(16)}`])
            ),
            bytes_uncompressed: 950,
        },
    },
]

export const BENCH_PROGRAMS: BenchProgram[] = [
    {
        id: 'noop',
        name: 'No-op passthrough (pure invocation overhead)',
        hog: `return record`,
        inputs: {},
    },
    {
        id: 'redact-attributes',
        name: 'Hash selected attribute keys with SHA256',
        hog: `
let rec := record
let keysToRedact := splitByString(',', inputs.redactKeys)
for (let key in keysToRedact) {
    let k := trim(key)
    if (not empty(rec.attributes?.[k])) {
        rec.attributes[k] := sha256Hex(concat(rec.attributes[k], inputs.salt))
    }
}
return rec
`,
        inputs: { redactKeys: 'user.email,distinct_id,card_number', salt: 'bench-salt' },
    },
    {
        id: 'body-regex-scrub',
        name: 'Regex scrub of emails and secret keys in body',
        hog: `
let rec := record
let body := rec.body
if (not empty(body)) {
    for (let pattern in [inputs.emailPattern, inputs.tokenPattern]) {
        let i := 0
        let found := extractRegex(body, pattern)
        while (i < 10 and notEmpty(found)) {
            body := replaceAll(body, found, '[REDACTED]')
            found := extractRegex(body, pattern)
            i := i + 1
        }
    }
    rec.body := body
}
return rec
`,
        inputs: {
            emailPattern: '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}',
            // Non-capturing group: extractRegex returns the first capture group when one
            // exists, and the scrub needs the whole token match.
            tokenPattern: 'sk_(?:fake|live|test)_[A-Za-z0-9]{10,}',
        },
    },
    {
        id: 'conditional-drop',
        name: 'Drop debug logs from a noisy service',
        hog: `
if (record.severity_text == 'debug' and record.service_name == inputs.noisyService) {
    return null
}
return record
`,
        inputs: { noisyService: 'edge-router' },
    },
]

// Preview of the globals shape planned for log transformations: the log record fields
// plus project context and resolved inputs. Buffers (trace/span ids) are excluded —
// the production globals builder will hex-encode them.
export function buildBenchGlobals(record: LogRecord, inputs: Record<string, unknown>): BenchGlobals {
    const { trace_id: _t, span_id: _s, ...rest } = record
    return {
        project: { id: 1, name: 'bench', url: 'http://localhost:8010/project/1' },
        record: { ...rest },
        inputs,
    }
}

import avro from 'avsc'
import { readFileSync } from 'fs'
import { join } from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { getDefaultLogsIngestionConsumerConfig, getDefaultTracesIngestionConsumerConfig } from '../config'
import { INTERNAL_LOGS_HEADER, signInternalLogs } from '../internal-logs'
import { encodeLogRecords } from '../log-record-avro'
import { librdKafkaError } from './parity-harness'
import type { ParityError, ParityHeader, ParityMessage, ParityScenario, ParityTeam } from './parity-types'

// Every Avro container gets a random sync marker, so a re-record rewrites the input bytes even when nothing else changed.
// No scenario relies on concurrent order: a sampling `rate_limit` bucket shared in one batch, or a metric-rule exemplar across messages.

// Mid-hour, so app metric hour truncation and the token bucket refill both show.
const PARITY_NOW_MS = Date.UTC(2025, 0, 15, 12, 37, 13, 250)
let NOW_MS = PARITY_NOW_MS
let NOW_MICROS = NOW_MS * 1000

/** The benchmark uses the real clock, because metric rules skip records older than 20 minutes. */
export function setGeneratorClock(nowMs: number = PARITY_NOW_MS): void {
    NOW_MS = nowMs
    NOW_MICROS = nowMs * 1000
}
const DAY_MICROS = 86_400_000_000
const SIGNING_KEY = 'parity-signing-key'

function loadSchema(name: 'logs' | 'traces'): avro.Type {
    const raw = readFileSync(join(__dirname, 'fixtures', 'schemas', `${name}.avsc.json`), 'utf8')
    return avro.Type.forSchema(parseJSON(raw))
}

export class Rng {
    constructor(private state: number) {}
    next(): number {
        this.state = (this.state + 0x6d2b79f5) | 0
        let t = this.state
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    int(maxExclusive: number): number {
        return Math.floor(this.next() * maxExclusive)
    }
    pick<T>(items: readonly T[]): T {
        return items[this.int(items.length)]
    }
    chance(p: number): boolean {
        return this.next() < p
    }
    bytes(n: number): Buffer {
        return Buffer.from(Array.from({ length: n }, () => this.int(256)))
    }
}

type Rec = Record<string, unknown>

export const TEAMS: ParityTeam[] = [
    { id: 101, api_token: 'phc_parity_plain', logs_settings: null },
    { id: 102, api_token: 'phc_parity_json', logs_settings: { json_parse_logs: true } },
    { id: 103, api_token: 'phc_parity_pii', logs_settings: { pii_scrub_logs: true } },
    {
        id: 104,
        api_token: 'phc_parity_both',
        logs_settings: { json_parse_logs: true, pii_scrub_logs: true, retention_days: 30 },
    },
    {
        id: 105,
        api_token: 'phc_parity_attr',
        logs_settings: { json_parse_logs: true, json_parse_logs_attribute_key: 'payload', retention_days: 90 },
    },
    { id: 106, api_token: 'phc_parity_ret7', logs_settings: { retention_days: 7 } },
]

export function jsonAttr(value: unknown): string {
    return JSON.stringify(value)
}

const BODIES: ((rng: Rng) => string)[] = [
    () => 'plain text log line',
    (rng) => `GET /api/users/${rng.int(100000)} 200 ${rng.int(900) + 10}ms`,
    () => 'user alice@example.com logged in from 192.168.1.20',
    () => 'card 4111 1111 1111 1111 exp 12/29 cvv 123',
    () => 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789 token=sk_live_FAKEFAKEFAKE1234',
    () => 'phone +1 (555) 123-4567 ssn 123-45-6789',
    () => 'request 3fa85f64-5717-4562-b3fc-2c963f66afa6 took 12ms on host ip-10-0-0-1',
    () => JSON.stringify({ level: 'info', msg: 'hello', user: { id: 7, email: 'bob@example.com' } }),
    () => JSON.stringify({ a: { b: { c: { d: [1, 2, { e: 'deep' }] } } }, '1': 'int-key', z: null, b: true }),
    () => JSON.stringify([1, 'two', { three: 3 }, [4, [5]]]),
    () => JSON.stringify({ big: 12345678901234567890, small: 1e-7, neg: -0, exp: 1e21, frac: 0.1 + 0.2 }),
    () => JSON.stringify(Object.fromEntries(Array.from({ length: 70 }, (_, i) => [`k${i}`, i]))),
    () => JSON.stringify({ arr: Array.from({ length: 80 }, (_, i) => i) }),
    () => JSON.stringify({ unicode: 'héllo wörld 🚀 ✓', 'emoji_key_🔥': 'fire', 'dotted.key': { nested: 'v' } }),
    () => '{"__proto__": "x", "constructor": "y", "toString": "z", "nested": {"__proto__": {"a": 1}}}',
    () => '{"dup": 1, "dup": 2, "other": "x"}',
    () => '  {"leading": "whitespace"}  ',
    () => '"just a json string"',
    () => '12345',
    () => '{not valid json',
    () => '',
    (rng) => JSON.stringify({ level: rng.pick(['debug', 'info', 'warn', 'error']), path: '/healthz', status: 200 }),
    (rng) => `ERROR something failed at ${new Date(NOW_MS - rng.int(1000000)).toISOString()} code=${rng.int(600)}`,
    () => JSON.stringify({ deep: parseJSON('['.repeat(140) + '1' + ']'.repeat(140)) }),
    () => 'x'.repeat(5000),
    () => JSON.stringify({ text: 'user 1234 paid $56.78 at 2025-01-15T10:00:00Z', other: 'x' }),
    () => JSON.stringify({ msg: 'escaped \\n newline and "quotes" and \t tabs', html: '<b>&amp;</b>' }),
]

const SEVERITIES: [string, number][] = [
    ['DEBUG', 5],
    ['INFO', 9],
    ['WARN', 13],
    ['ERROR', 17],
    ['info', 9],
    ['', 0],
]

export function makeLogRecord(rng: Rng, i: number, overrides: Rec = {}): Rec {
    const [severityText, severityNumber] = rng.pick(SEVERITIES)
    const attributes: Record<string, string> = {}
    const attributeCount = rng.int(6)
    for (let a = 0; a < attributeCount; a++) {
        const key = rng.pick(['http.method', 'url.path', 'user.email', 'count', 'payload', 'ip', 'k', '1', 'level'])
        attributes[key] = rng.pick([
            jsonAttr('GET'),
            jsonAttr('/healthz'),
            jsonAttr('/api/v1/items'),
            jsonAttr('carol@example.com'),
            jsonAttr(42),
            jsonAttr(3.5),
            jsonAttr(true),
            jsonAttr({ nested: { json: 'payload', n: 1 } }),
            jsonAttr(JSON.stringify({ stringified: 'json', arr: [1, 2] })),
            'raw-unquoted',
            jsonAttr('10.1.2.3'),
        ])
    }
    const resource: Record<string, string> = {
        'service.name': jsonAttr(rng.pick(['api', 'worker', 'web'])),
    }
    if (rng.chance(0.5)) {
        resource['k8s.pod.name'] = jsonAttr(`pod-${rng.int(5)}`)
    }
    return {
        uuid: `00000000-0000-4000-8000-${String(i).padStart(12, '0')}`,
        // Rate sampling falls back to Math.random for a record without a trace id, which no fixture can pin.
        trace_id: rng.bytes(16),
        span_id: rng.chance(0.8) ? rng.bytes(8) : null,
        trace_flags: rng.chance(0.5) ? 1 : null,
        timestamp: NOW_MICROS - rng.int(3_600_000_000),
        observed_timestamp: NOW_MICROS,
        body: rng.pick(BODIES)(rng),
        severity_text: severityText,
        severity_number: severityNumber,
        service_name: rng.pick(['api', 'worker', 'web', null]),
        resource_attributes: rng.chance(0.9) ? resource : null,
        instrumentation_scope: rng.pick([null, 'io.opentelemetry.http', 'scope@1.0']),
        event_name: rng.pick([null, 'request', 'job.done']),
        attributes: rng.chance(0.9) ? attributes : null,
        bytes_uncompressed: rng.chance(0.9) ? 50 + rng.int(800) : null,
        retention_days: null,
        pattern: null,
        pattern_version: null,
        ...overrides,
    }
}

export function makeSpanRecord(rng: Rng, i: number): Rec {
    return {
        uuid: `00000000-0000-4000-9000-${String(i).padStart(12, '0')}`,
        trace_id: rng.bytes(16),
        span_id: rng.bytes(8),
        parent_span_id: rng.chance(0.5) ? rng.bytes(8) : null,
        trace_state: null,
        name: rng.pick(['GET /api', 'db.query', 'job']),
        kind: rng.int(6),
        flags: 1,
        timestamp: NOW_MICROS - rng.int(3_600_000_000),
        end_time: NOW_MICROS,
        observed_timestamp: NOW_MICROS,
        service_name: rng.pick(['api', 'worker']),
        resource_attributes: { 'service.name': jsonAttr('api') },
        instrumentation_scope: null,
        attributes: {
            'http.status_code': jsonAttr(rng.pick([200, 404, 500])),
            'user.email': jsonAttr('d@example.com'),
        },
        dropped_attributes_count: 0,
        events: [],
        dropped_events_count: 0,
        links: [],
        dropped_links_count: 0,
        status_code: rng.int(3),
        status_message: null,
        bytes_uncompressed: 100 + rng.int(400),
        retention_days: null,
    }
}

/** `encodeLogRecords` registers zstandard only, which hides avsc's built-in null and deflate codecs. */
function encodeWithBuiltinCodec(type: avro.Type, codec: string, records: Rec[]): Promise<Buffer> {
    return new Promise((resolve, reject) => {
        const buffers: Buffer[] = []
        const encoder = new avro.streams.BlockEncoder(type, { codec })
        encoder.on('data', (buf: Buffer) => buffers.push(buf))
        encoder.on('end', () => resolve(Buffer.concat(buffers)))
        encoder.on('error', reject)
        for (const record of records) {
            encoder.write(record)
        }
        encoder.end()
    })
}

type MessageOptions = {
    headers?: Record<string, string>
    omitHeaders?: string[]
    omitSizeHeaders?: boolean
    codec?: 'zstandard' | 'null' | 'deflate'
    schema?: 'logs' | 'traces'
    rawValue?: Buffer | null
    key?: string
}

export class MessageFactory {
    private offset = 0
    constructor(
        private readonly rng: Rng,
        private readonly topic = 'logs_ingestion'
    ) {}

    async make(team: ParityTeam | string, records: Rec[], options: MessageOptions = {}): Promise<ParityMessage> {
        const token = typeof team === 'string' ? team : team.api_token
        let value: Buffer | null
        if (options.rawValue !== undefined) {
            value = options.rawValue
        } else if ((options.codec ?? 'zstandard') === 'zstandard') {
            value = await encodeLogRecords(loadSchema(options.schema ?? 'logs'), 'zstandard', records as any)
        } else {
            value = await encodeWithBuiltinCodec(loadSchema(options.schema ?? 'logs'), options.codec!, records)
        }
        const bytes = value?.length ?? 0
        const headers: Record<string, string> = { token }
        if (!options.omitSizeHeaders) {
            headers.bytes_uncompressed = String(bytes * 3)
            headers.bytes_uncompressed_records = String(bytes * 2)
            headers.bytes_compressed = String(bytes)
            headers.record_count = String(records.length)
        }
        headers.created_at = new Date(NOW_MS - 1000 - this.rng.int(20_000)).toISOString()
        for (const name of options.omitHeaders ?? []) {
            delete headers[name]
        }
        Object.assign(headers, options.headers ?? {})
        const headerList: ParityHeader[] = Object.entries(headers)
        return {
            topic: this.topic,
            partition: this.rng.int(4),
            offset: this.offset++,
            timestamp: NOW_MS - 1000,
            key: options.key ?? null,
            headers: headerList,
            value_b64: value === null ? null : value.toString('base64'),
        }
    }

    async logs(team: ParityTeam | string, count: number, options: MessageOptions = {}, overrides: Rec = {}) {
        const records = Array.from({ length: count }, (_, i) =>
            makeLogRecord(this.rng, this.offset * 1000 + i, overrides)
        )
        return this.make(team, records, options)
    }
}

const RESOLVED_DEFAULT_CONFIG = (): Record<string, string | number | boolean> => ({
    ...(getDefaultLogsIngestionConsumerConfig() as unknown as Record<string, string | number | boolean>),
    ...(getDefaultTracesIngestionConsumerConfig() as unknown as Record<string, string | number | boolean>),
    // The consumers connect through LOGS_REDIS_HOST and TRACES_REDIS_HOST, so the fallback URL stays empty.
    REDIS_URL: '',
    REDIS_POOL_MIN_SIZE: 1,
    REDIS_POOL_MAX_SIZE: 3,
    LOGS_REDIS_HOST: '127.0.0.1',
    LOGS_REDIS_PORT: 6379,
    LOGS_REDIS_TLS: false,
    TRACES_REDIS_HOST: '127.0.0.1',
    TRACES_REDIS_PORT: 6379,
    TRACES_REDIS_TLS: false,
    // Pinned to the non-production values, which several defaults derive from the environment.
    LOGS_LIMITER_ENABLED_TEAMS: '*',
    TRACES_LIMITER_ENABLED_TEAMS: '*',
    LOGS_BACKFILL_ENABLED_TEAMS: '',
    LOGS_RETENTION_ENABLED_TEAMS: '',
    TRACES_RETENTION_ENABLED_TEAMS: '',
    LOGS_METRICS_RULES_ENABLED_TEAMS: '',
    TRACES_METRICS_RULES_ENABLED_TEAMS: '',
    LOGS_DEFAULT_METRIC_RULES_ENABLED_TEAMS: '',
    TRACES_DEFAULT_METRIC_RULES_ENABLED_TEAMS: '',
    LOGS_SAMPLING_ENABLED_TEAMS: '',
    LOGS_TRANSFORMATIONS_ENABLED_TEAMS: '',
    LOGS_PATTERN_MASKING_ENABLED_TEAMS: '',
    LOGS_JSON_ATTRIBUTE_PARSING_ENABLED_TEAMS: '',
    LOGS_JSON_ATTRIBUTE_EXTRACTION_ENABLED_TEAMS: '',
    LOGS_INTERNAL_INGESTION_ENABLED_TEAMS: '',
    LOGS_INTERNAL_INGESTION_SIGNING_KEYS: '',
    LOGS_BILLING_PRORATE_ENABLED: false,
})

export function baseScenario(
    name: string,
    description: string,
    overrides: Record<string, string | number | boolean> = {}
): ParityScenario {
    return {
        name,
        description,
        consumer: 'logs',
        batch_now_ms: [],
        config: { ...RESOLVED_DEFAULT_CONFIG(), ...overrides },
        teams: TEAMS,
        quota_limited_tokens: [],
        sampling_rules: {},
        retention_rules: {},
        metric_rules: {},
        pattern_message_keys: {},
        traces_retention_days: {},
        team_lookup_faults: {},
        team_by_id_faults: {},
        team_by_id_missing: [],
        metric_rules_faults: {},
        metric_emit_faults: [],
        pattern_keys_faults: {},
        omit_deps: [],
        produce_faults: [],
        batches: [],
    }
}

export function finish(scenario: ParityScenario, clocks?: number[]): ParityScenario {
    scenario.batch_now_ms = clocks ?? scenario.batches.map(() => NOW_MS)
    return scenario
}

export const leaf = (key: string, operator: string, value: unknown, type = 'log_attribute'): Rec => ({
    key,
    operator,
    value,
    type,
})
export const group = (type: 'AND' | 'OR', ...values: Rec[]): Rec => ({ type: 'AND', values: [{ type, values }] })
const err = (name: string, message: string, dependencyUnavailable = false): ParityError => ({
    name,
    message,
    dependency_unavailable: dependencyUnavailable,
})
// The fixture stores the message the consumer sees, so Rust can quarantine with the same headers.
const kafkaErr = (code: number): ParityError => ({ ...err('Error', librdKafkaError(code).message), kafka_code: code })
export const severityRule = (id: string, actions: Rec, scope_service: string | null = null): Rec => ({
    id,
    rule_type: 'severity_sampling',
    scope_service,
    scope_path_pattern: null,
    scope_attribute_filters: [],
    config: { actions },
})
export const pathRule = (id: string, config: Rec, scope_service: string | null = null): Rec => ({
    id,
    rule_type: 'path_drop',
    scope_service,
    scope_path_pattern: null,
    scope_attribute_filters: [],
    config,
})
export const rateRule = (id: string, config: Rec): Rec => ({
    id,
    rule_type: 'rate_limit',
    scope_service: null,
    scope_path_pattern: null,
    scope_attribute_filters: [],
    config,
})

export async function buildParityScenarios(): Promise<ParityScenario[]> {
    setGeneratorClock()
    const scenarios: ParityScenario[] = []
    const [plain, json, pii, both, attr, ret7] = TEAMS

    {
        const rng = new Rng(1)
        const f = new MessageFactory(rng)
        const s = baseScenario('passthrough', 'No settings or rules: every message is forwarded byte for byte.')
        s.batches = [
            [
                await f.logs(plain, 3, { key: 'some-key' }),
                await f.logs(plain, 1, {
                    headers: {
                        // Inputs that name reserved output headers, which the consumer must overwrite.
                        team_id: '999',
                        'retention-days': '999',
                        'json-parse': 'maybe',
                        source_topic: 'spoofed',
                        source_partition: '77',
                        'internal-source': 'spoofed',
                        'x-custom-header': 'kept as is',
                    },
                }),
                await f.logs(ret7, 2, { omitHeaders: ['created_at'] }),
                await f.logs(ret7, 1, { headers: { created_at: 'not a date' } }),
            ],
        ]
        scenarios.push(finish(s))
    }
    {
        const rng = new Rng(2)
        const f = new MessageFactory(rng)
        const s = baseScenario('normalize', 'JSON body parse, PII scrub and both, across the body corpus.')
        const batch: ParityMessage[] = []
        for (const team of [json, pii, both]) {
            for (let i = 0; i < BODIES.length; i++) {
                const records = [makeLogRecord(rng, i, { body: BODIES[i](rng) }), makeLogRecord(rng, i + 100)]
                batch.push(await f.make(team, records))
            }
        }
        s.batches = [batch]
        scenarios.push(finish(s))
    }
    {
        const rng = new Rng(3)
        const f = new MessageFactory(rng)
        const s = baseScenario('json-attribute', 'Selected-attribute JSON parsing, sniffing and extraction gates.', {
            LOGS_JSON_ATTRIBUTE_PARSING_ENABLED_TEAMS: '105',
            LOGS_JSON_ATTRIBUTE_EXTRACTION_ENABLED_TEAMS: '105',
        })
        const payloads = [
            jsonAttr({ user: { id: 1, email: 'e@example.com' }, list: [1, 2, 3], ok: true }),
            jsonAttr(JSON.stringify({ double: 'encoded', n: 2 })),
            jsonAttr('not an object'),
            jsonAttr([1, 2]),
            '{"raw": "object", "x": 1}',
            jsonAttr(Object.fromEntries(Array.from({ length: 60 }, (_, i) => [`f${i}`, i]))),
            'garbage{',
            '  \\n{"escaped": "lead"}',
        ]
        const batch: ParityMessage[] = []
        for (const payload of payloads) {
            const record = makeLogRecord(rng, batch.length, { attributes: { payload, keep: jsonAttr('me') } })
            batch.push(await f.make(attr, [record]))
        }
        s.batches = [batch]
        scenarios.push(finish(s))
    }
    {
        const rng = new Rng(4)
        const f = new MessageFactory(rng)
        const s = baseScenario(
            'parse-failures',
            'Missing token, unknown team, bad size headers, broken avro, null value.'
        )
        s.team_lookup_faults = {
            phc_lookup_error: err('Error', 'lookup exploded'),
            phc_lookup_outage: err('Error', 'postgres down', true),
        }
        s.batches = [
            [
                await f.logs(plain, 1, { headers: { token: '' } }),
                await f.logs(plain, 1, { omitHeaders: ['token'] }),
                await f.logs('phc_unknown_token', 1),
                await f.logs('phc_lookup_error', 1),
                await f.logs('phc_lookup_outage', 1),
                await f.logs(plain, 1, { headers: { bytes_uncompressed: '-5' } }),
                await f.logs(plain, 1, { headers: { record_count: 'abc' } }),
                await f.logs(plain, 1, { headers: { bytes_compressed: '12abc' } }),
                await f.logs(plain, 1, { headers: { bytes_uncompressed: '1e3', record_count: '  7' } }),
                await f.logs(plain, 1, { omitSizeHeaders: true }),
                await f.make(plain, [], { rawValue: Buffer.from('not avro at all, plain team') }),
                await f.make(json, [], { rawValue: Buffer.from('not avro at all, json team') }),
                await f.make(json, [], { rawValue: Buffer.from('Obj\u0001truncated container') }),
                await f.make(plain, [], { rawValue: null }),
                await f.make(json, [], { rawValue: null }),
                await f.make(json, []),
                await f.logs(json, 2, { headers: { min_timestamp: 'garbage' } }),
                await f.logs(json, 2, { headers: { min_timestamp: '1.5' } }),
            ],
        ]
        scenarios.push(finish(s))
    }
    {
        const rng = new Rng(5)
        const f = new MessageFactory(rng)
        const s = baseScenario(
            'gates',
            'Backfill gate, quota limits and partial rate-limit admission over two batches.',
            {
                LOGS_BACKFILL_ENABLED_TEAMS: '102',
                LOGS_LIMITER_BUCKET_SIZE_KB: 20,
                LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND: 2,
                LOGS_LIMITER_TEAM_BUCKET_SIZE_KB: '104:100000',
                LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: '104:100000',
                LOGS_LIMITER_DISABLED_FOR_TEAMS: '106',
            }
        )
        s.quota_limited_tokens = [pii.api_token]
        s.batches = [
            [
                await f.logs(plain, 2, { headers: { backfill_days: '3' } }),
                await f.logs(json, 2, { headers: { backfill_days: '3' } }),
                await f.logs(pii, 2),
                await f.logs(plain, 8),
                await f.logs(plain, 1),
                await f.logs(plain, 6),
                await f.logs(plain, 1),
                await f.logs(both, 6),
                await f.logs(ret7, 6),
                await f.logs(ret7, 6),
            ],
            [await f.logs(plain, 1), await f.logs(plain, 6), await f.logs(both, 3), await f.logs(ret7, 1)],
        ]
        // The second batch runs 5 seconds later, so the buckets have refilled part way.
        scenarios.push(finish(s, [NOW_MS, NOW_MS + 5000]))
    }
    {
        const rng = new Rng(6)
        const f = new MessageFactory(rng)
        const s = baseScenario('sampling', 'Severity sampling, path drops and attribute filters with billing credit.', {
            LOGS_SAMPLING_ENABLED_TEAMS: '101,102',
            LOGS_BILLING_PRORATE_ENABLED: true,
        })
        s.sampling_rules = {
            101: [
                severityRule('sev-drop-debug', {
                    DEBUG: { type: 'drop' },
                    INFO: { type: 'sample', rate: 0.5 },
                    WARN: { type: 'keep' },
                    ERROR: { type: 'keep' },
                }),
                pathRule('path-healthz', { patterns: ['/healthz', '^/internal/.*'] }),
            ],
            102: [
                pathRule(
                    'attr-filter-drop',
                    {
                        patterns: ['GET'],
                        match_attribute_key: 'http.method',
                        filter_group: group(
                            'OR',
                            leaf('user.email', 'icontains', 'EXAMPLE.COM'),
                            leaf('count', 'gt', 10),
                            leaf('message', 'regex', 'healthz|token=', 'log')
                        ),
                    },
                    'api'
                ),
                pathRule('path-items', { patterns: ['/api/v1'], match_attribute_key: 'url.path' }),
            ],
        }
        const batch: ParityMessage[] = []
        for (const team of [plain, json]) {
            for (let m = 0; m < 8; m++) {
                const records = Array.from({ length: 1 + rng.int(8) }, (_, i) =>
                    makeLogRecord(rng, m * 100 + i, {
                        severity_text: rng.pick(['INFO', 'INFO', 'WARN', 'DEBUG', 'ERROR']),
                        service_name: rng.pick(['api', 'web']),
                        attributes: {
                            'url.path': jsonAttr(rng.pick(['/healthz', '/internal/x', '/api/v1/items', '/ok'])),
                            'http.method': jsonAttr(rng.pick(['GET', 'POST'])),
                            count: jsonAttr(rng.int(20)),
                        },
                    })
                )
                batch.push(await f.make(team, records))
            }
        }
        batch.push(await f.logs(plain, 3, {}, { severity_text: 'DEBUG', severity_number: 5, attributes: null }))
        s.batches = [batch]
        scenarios.push(finish(s))
    }
    {
        const rng = new Rng(16)
        const f = new MessageFactory(rng)
        const s = baseScenario(
            'sampling-rate-limit',
            'Rate-limit drop rules counting records and bytes, across batches.',
            {
                LOGS_SAMPLING_ENABLED_TEAMS: '*',
                LOGS_BILLING_PRORATE_ENABLED: true,
            }
        )
        s.sampling_rules = {
            104: [rateRule('rate-records', { logs_per_second: 2, burst_logs: 3 })],
            102: [rateRule('rate-bytes', { kb_per_second: 1, burst_kb: 2 })],
        }
        // One message per team per batch: messages of one batch reach the bucket in no fixed order.
        s.batches = [
            [await f.logs(both, 6), await f.logs(json, 8)],
            [await f.logs(both, 5), await f.logs(json, 8)],
            [await f.logs(both, 5), await f.logs(json, 8)],
        ]
        scenarios.push(finish(s, [NOW_MS, NOW_MS + 1500, NOW_MS + 60_000]))
    }
    {
        const rng = new Rng(7)
        const f = new MessageFactory(rng)
        const s = baseScenario('retention', 'Per-row retention rules and expired-row drops from backdated imports.', {
            LOGS_RETENTION_ENABLED_TEAMS: '*',
            LOGS_BACKFILL_ENABLED_TEAMS: '*',
            LOGS_BILLING_PRORATE_ENABLED: true,
        })
        const rules = [
            {
                id: 'ret-errors-90',
                config: {
                    retention_days: 90,
                    filter_group: group('AND', leaf('severity_text', 'exact', ['ERROR'], 'log')),
                },
            },
            {
                id: 'ret-worker-30',
                config: {
                    retention_days: 30,
                    filter_group: group('AND', leaf('service_name', 'exact', 'worker', 'log')),
                },
            },
            {
                id: 'ret-invalid-days',
                config: { retention_days: 7, filter_group: group('AND', leaf('k', 'is_set', null)) },
            },
            { id: 'ret-invalid-type', config: { retention_days: 'forever' } },
            { id: 'ret-null-group', config: { retention_days: 60 } },
        ]
        s.retention_rules = { 101: { logs: rules }, 105: { logs: rules } }
        const old = (days: number) => NOW_MICROS - days * DAY_MICROS
        const batch: ParityMessage[] = []
        for (const team of [plain, ret7, both, attr]) {
            const records = [
                makeLogRecord(rng, 1, { timestamp: old(1), severity_text: 'INFO', service_name: 'api' }),
                makeLogRecord(rng, 2, { timestamp: old(20), severity_text: 'ERROR', service_name: 'api' }),
                makeLogRecord(rng, 3, { timestamp: old(40), severity_text: 'INFO', service_name: 'worker' }),
                makeLogRecord(rng, 4, { timestamp: old(40), severity_text: 'INFO', service_name: 'api' }),
                makeLogRecord(rng, 5, { timestamp: old(100), severity_text: 'ERROR', service_name: 'api' }),
                makeLogRecord(rng, 6, { timestamp: null }),
            ]
            batch.push(
                await f.make(team, records, { headers: { min_timestamp: String(old(100)), backfill_days: '100' } })
            )
            batch.push(await f.make(team, records.slice(3, 4), { headers: { min_timestamp: String(old(40)) } }))
            batch.push(await f.make(team, records.slice(0, 1), { headers: { min_timestamp: String(old(1)) } }))
        }
        s.batches = [batch]
        scenarios.push(finish(s))
    }
    {
        const rng = new Rng(8)
        const f = new MessageFactory(rng)
        const s = baseScenario('pattern-masking', 'Pattern masking with default and team-configured message keys.', {
            LOGS_PATTERN_MASKING_ENABLED_TEAMS: '101,102,104',
        })
        s.pattern_message_keys = { 102: ['text', 'nope'] }
        s.pattern_keys_faults = { 104: { ...err('Error', 'postgres blip', true), times: 1 } }
        const batch: ParityMessage[] = []
        for (const team of [plain, json, pii, both]) {
            for (let i = 0; i < 6; i++) {
                batch.push(await f.logs(team, 4))
            }
        }
        s.batches = [batch]
        scenarios.push(finish(s))

        const s2 = baseScenario('pattern-masking-outage', 'A pattern key outage that outlasts the retries.', {
            LOGS_PATTERN_MASKING_ENABLED_TEAMS: '*',
        })
        s2.pattern_keys_faults = { 101: { ...err('Error', 'postgres down', true), times: 10 } }
        s2.batches = [[await f.logs(plain, 2), await f.logs(json, 2)], [await f.logs(json, 1)]]
        scenarios.push(finish(s2))

        const s3 = baseScenario(
            'pattern-masking-no-cache',
            'Pattern masking without a key cache uses the default keys.',
            {
                LOGS_PATTERN_MASKING_ENABLED_TEAMS: '*',
            }
        )
        s3.omit_deps = ['patternMessageKeysCache']
        s3.batches = [[await f.logs(plain, 4), await f.logs(json, 4)]]
        scenarios.push(finish(s3))
    }
    {
        const rng = new Rng(9)
        const f = new MessageFactory(rng)
        const s = baseScenario('metric-rules', 'Team metric rules plus the built-in default rules, over two batches.', {
            LOGS_METRICS_RULES_ENABLED_TEAMS: '101,102,104,106',
            LOGS_DEFAULT_METRIC_RULES_ENABLED_TEAMS: '102,103',
        })
        s.metric_rules = {
            101: [
                {
                    id: 'count-errors',
                    metric_name: 'errors_total',
                    filter_group: group('AND', leaf('severity_text', 'exact', 'ERROR', 'log')),
                    value_attribute: null,
                    group_by: ['service_name', 'attributes.http.method'],
                },
                {
                    id: 'sum-count',
                    metric_name: 'count_sum',
                    filter_group: null,
                    value_attribute: 'count',
                    group_by: ['severity_text'],
                },
                {
                    id: 'span-rule-ignored',
                    metric_name: 'spans_total',
                    filter_group: null,
                    value_attribute: null,
                    group_by: [],
                    source: 'spans',
                },
            ],
            104: [
                {
                    id: 'by-pod',
                    metric_name: 'by_pod',
                    filter_group: null,
                    value_attribute: null,
                    group_by: ['resource_attributes.k8s.pod.name'],
                },
            ],
            106: [{ id: 'emit-fails', metric_name: 'm', filter_group: null, value_attribute: null, group_by: [] }],
        }
        s.metric_rules_faults = { 104: err('Error', 'rules fetch failed') }
        s.metric_emit_faults = [106]
        // One message per team per batch: the exemplar is the first matching record across messages.
        const batches: ParityMessage[][] = []
        for (let b = 0; b < 2; b++) {
            const batch: ParityMessage[] = []
            for (const team of [plain, json, pii, both, ret7]) {
                batch.push(await f.logs(team, 3 + rng.int(6)))
            }
            batches.push(batch)
        }
        s.batches = batches
        // The second batch is in the next hour, which resets series admission.
        scenarios.push(finish(s, [NOW_MS, NOW_MS + 3_600_000]))
    }
    {
        const rng = new Rng(10)
        const f = new MessageFactory(rng)
        const s = baseScenario(
            'internal-logs',
            'Signed internal batches: unbilled, billed, wrong team, stale and forged.',
            {
                LOGS_INTERNAL_INGESTION_SIGNING_KEYS: `${SIGNING_KEY},older-key`,
                LOGS_INTERNAL_INGESTION_ENABLED_TEAMS: '101,102',
                LOGS_SAMPLING_ENABLED_TEAMS: '*',
                LOGS_RETENTION_ENABLED_TEAMS: '*',
            }
        )
        s.internal_source_policies = {
            hog_flow: { billed: false, teamRules: false },
            billed_src: { billed: true, teamRules: true },
            rules_src: { billed: false, teamRules: true },
        }
        s.sampling_rules = { 101: [severityRule('drop-all-debug', { DEBUG: { type: 'drop' } })] }
        s.retention_rules = {
            101: {
                logs: [
                    { id: 'r', config: { retention_days: 30, filter_group: group('AND', leaf('k', 'is_set', null)) } },
                ],
            },
        }
        const signedAt = new Date(NOW_MS - 2000)
        const created = new Date(NOW_MS - 1000).toISOString()
        const sign = (source: string, teamId: number, at = signedAt, key = SIGNING_KEY) =>
            signInternalLogs(key, source, teamId, at)
        const internal = (signature: string, extra: Record<string, string> = {}) => ({
            headers: { [INTERNAL_LOGS_HEADER]: signature, created_at: created, ...extra },
        })
        const old = (days: number) => String(NOW_MICROS - days * DAY_MICROS)
        s.batches = [
            [
                await f.logs(plain, 3, internal(sign('hog_flow', 101))),
                await f.logs(json, 2, internal(sign('hog_flow', 102))),
                await f.logs(both, 2, internal(sign('hog_flow', 104))),
                await f.logs(plain, 2, internal(sign('hog_flow', 102))),
                await f.logs(plain, 2, internal(sign('hog_flow', 101, new Date(NOW_MS - 3_600_000)))),
                await f.logs(plain, 2, internal(sign('unknown_src', 101))),
                await f.logs(plain, 2, internal('v1.hog_flow.1736942398.deadbeef')),
                await f.logs(plain, 2, internal(sign('hog_flow', 101, signedAt, 'older-key'))),
                await f.logs(plain, 2, { headers: { 'internal-source': 'spoofed' } }),
                await f.logs(plain, 2, internal(sign('hog_flow', 101), { backfill_days: '2' })),
                await f.logs(plain, 3, internal(sign('billed_src', 101))),
                await f.logs(plain, 3, internal(sign('rules_src', 101))),
                await f.logs(plain, 3, internal(sign('hog_flow', 101), { min_timestamp: old(3) }), {
                    timestamp: Number(old(3)),
                }),
                await f.logs(plain, 3, internal(sign('rules_src', 101), { min_timestamp: old(20) }), {
                    timestamp: Number(old(20)),
                }),
            ],
        ]
        scenarios.push(finish(s))
    }
    {
        const rng = new Rng(11)
        const f = new MessageFactory(rng)
        const s = baseScenario('faults', 'Produce failures route to the DLQ; app metric failures are logged.')
        s.produce_faults = [
            { output: 'logs', team_id: '102', times: 1, error: err('MessageSizeTooLarge', 'too big') },
            { output: 'app_metrics', times: 1, error: err('KafkaError', 'metrics down') },
        ]
        s.batches = [[await f.logs(plain, 2), await f.logs(json, 2), await f.logs(json, 1)], [await f.logs(plain, 1)]]
        scenarios.push(finish(s))

        const s2 = baseScenario('faults-dlq-down', 'A failed DLQ write after a failed produce fails the batch.', {
            LOGS_BACKFILL_ENABLED_TEAMS: '',
        })
        s2.produce_faults = [
            { output: 'logs', team_id: '102', times: 1, error: err('MessageSizeTooLarge', 'too big') },
            { output: 'logs_dlq', times: 10, error: err('KafkaError', 'dlq down') },
        ]
        // The backfill drop queues a usage row in the failed batch, which the next batch flushes.
        s2.batches = [
            [
                await f.logs(plain, 2),
                await f.logs(json, 2),
                await f.logs(plain, 1, { headers: { backfill_days: '1' } }),
            ],
            [await f.logs(plain, 1)],
        ]
        scenarios.push(finish(s2))

        const s3 = baseScenario('faults-dependency', 'A dependency outage on produce outlasts the retries.')
        s3.produce_faults = [
            { output: 'logs', team_id: '101', times: 10, error: err('Error', 'kafka unavailable', true) },
        ]
        s3.batches = [[await f.logs(plain, 2), await f.logs(json, 2)], [await f.logs(json, 1)]]
        scenarios.push(finish(s3))

        const s4 = baseScenario('faults-transient', 'Dependency blips shorter than the retries are absorbed.')
        s4.produce_faults = [{ output: 'logs', team_id: '101', times: 1, error: err('Error', 'blip', true) }]
        s4.team_by_id_faults = { 102: { ...err('Error', 'pg blip', true), times: 1 } }
        s4.batches = [[await f.logs(plain, 2), await f.logs(json, 2)]]
        scenarios.push(finish(s4))

        const s5 = baseScenario('faults-team-by-id', 'The team lookup during processing fails or finds no team.')
        s5.team_by_id_faults = {
            101: { ...err('Error', 'pg down', true), times: 10 },
            102: { ...err('TypeError', 'bad row'), times: 1 },
        }
        s5.team_by_id_missing = [104]
        s5.batches = [[await f.logs(plain, 1), await f.logs(json, 2), await f.logs(both, 2)], [await f.logs(both, 1)]]
        scenarios.push(finish(s5))
    }
    {
        const rng = new Rng(12)
        const f = new MessageFactory(rng, 'traces_ingestion')
        const s = baseScenario('traces', 'The traces consumer: spans schema, spans retention and metric rules.', {
            TRACES_RETENTION_ENABLED_TEAMS: '101',
            TRACES_METRICS_RULES_ENABLED_TEAMS: '101',
            LOGS_PATTERN_MASKING_ENABLED_TEAMS: '*',
            LOGS_SAMPLING_ENABLED_TEAMS: '102',
            LOGS_BACKFILL_ENABLED_TEAMS: '101',
            LOGS_INTERNAL_INGESTION_SIGNING_KEYS: SIGNING_KEY,
            LOGS_INTERNAL_INGESTION_ENABLED_TEAMS: '*',
        })
        s.consumer = 'traces'
        s.quota_limited_tokens = [pii.api_token]
        s.traces_retention_days = { 101: 60, 102: 14 }
        s.sampling_rules = {
            102: [pathRule('span-drop', { patterns: ['db.query'], match_attribute_key: 'name' })],
        }
        s.retention_rules = {
            101: {
                spans: [
                    {
                        id: 'span-ret',
                        config: {
                            retention_days: 90,
                            filter_group: group('AND', leaf('name', 'exact', 'job', 'span_attribute')),
                        },
                    },
                ],
                logs: [
                    {
                        id: 'logs-rule-ignored',
                        config: { retention_days: 30, filter_group: group('AND', leaf('k', 'is_set', null)) },
                    },
                ],
            },
        }
        s.metric_rules = {
            101: [
                {
                    id: 'span-count',
                    metric_name: 'span_count',
                    filter_group: null,
                    value_attribute: null,
                    group_by: ['service_name', 'name', 'kind', 'status_code'],
                    source: 'spans',
                },
                { id: 'log-rule-ignored', metric_name: 'l', filter_group: null, value_attribute: null, group_by: [] },
            ],
        }
        const spans = (n: number) => Array.from({ length: n }, (_, i) => makeSpanRecord(rng, rng.int(1_000_000) + i))
        s.batches = [
            [
                await f.make(plain, spans(4), { schema: 'traces' }),
                await f.make(json, spans(4), { schema: 'traces' }),
                await f.make(pii, spans(2), { schema: 'traces' }),
                await f.make(plain, spans(2), { schema: 'traces', headers: { backfill_days: '2' } }),
                await f.make(json, spans(2), { schema: 'traces', headers: { backfill_days: '2' } }),
                await f.make(plain, spans(2), {
                    schema: 'traces',
                    headers: {
                        [INTERNAL_LOGS_HEADER]: signInternalLogs(SIGNING_KEY, 'hog_flow', 101, new Date(NOW_MS - 2000)),
                    },
                }),
            ],
        ]
        scenarios.push(finish(s))

        const s2 = baseScenario(
            'traces-no-config-cache',
            'Traces without the tracing config cache use the built-in default.'
        )
        s2.consumer = 'traces'
        s2.omit_deps = ['tracingConfigCache']
        s2.batches = [[await f.make(plain, spans(2), { schema: 'traces' })]]
        scenarios.push(finish(s2))
    }
    {
        const rng = new Rng(13)
        const f = new MessageFactory(rng)
        const s = baseScenario('codecs', 'Null and deflate container codecs, with and without re-encode.')
        const batch: ParityMessage[] = []
        for (const codec of ['null', 'deflate', 'zstandard'] as const) {
            batch.push(await f.logs(plain, 2, { codec }))
            batch.push(await f.logs(json, 2, { codec }))
        }
        s.batches = [batch]
        scenarios.push(finish(s))
    }
    {
        const rng = new Rng(14)
        const f = new MessageFactory(rng)
        const s = baseScenario('fuzz', 'Seeded random mix of every feature, for coverage the hand cases miss.', {
            LOGS_SAMPLING_ENABLED_TEAMS: '*',
            LOGS_RETENTION_ENABLED_TEAMS: '*',
            LOGS_PATTERN_MASKING_ENABLED_TEAMS: '*',
            LOGS_JSON_ATTRIBUTE_PARSING_ENABLED_TEAMS: '*',
            LOGS_JSON_ATTRIBUTE_EXTRACTION_ENABLED_TEAMS: '*',
            LOGS_BACKFILL_ENABLED_TEAMS: '101,104',
            LOGS_BILLING_PRORATE_ENABLED: true,
        })
        s.quota_limited_tokens = [TEAMS[5].api_token]
        s.sampling_rules = {
            102: [severityRule('fuzz-sev', { DEBUG: { type: 'drop' }, INFO: { type: 'sample', rate: 0.3 } }, 'web')],
            104: [pathRule('fuzz-path', { patterns: ['/api/v1'], match_attribute_key: 'url.path' })],
        }
        s.retention_rules = {
            103: {
                logs: [
                    {
                        id: 'fuzz-ret',
                        config: { retention_days: 30, filter_group: group('AND', leaf('k', 'is_set', null)) },
                    },
                ],
            },
        }
        const batches: ParityMessage[][] = []
        for (let b = 0; b < 3; b++) {
            const batch: ParityMessage[] = []
            for (let m = 0; m < 40; m++) {
                const team = rng.pick(TEAMS)
                const headers: Record<string, string> = {}
                if (rng.chance(0.1)) {
                    headers.backfill_days = '2'
                }
                if (rng.chance(0.2)) {
                    headers.min_timestamp = String(NOW_MICROS - rng.int(60) * DAY_MICROS)
                }
                batch.push(await f.logs(team, 1 + rng.int(8), { headers }))
            }
            batches.push(batch)
        }
        s.batches = batches
        scenarios.push(finish(s, [NOW_MS, NOW_MS + 1000, NOW_MS + 2000]))
    }
    {
        const rng = new Rng(17)
        const f = new MessageFactory(rng)
        const s = baseScenario(
            'faults-kafka-delivery',
            'A Kafka outage on the logs produce replays the batch; a bad record still goes to the DLQ.'
        )
        s.produce_faults = [
            { output: 'logs', team_id: '101', times: 1, error: kafkaErr(-192) },
            { output: 'logs', team_id: '102', times: 1, error: kafkaErr(87) },
            {
                output: 'logs',
                team_id: '104',
                times: 10,
                error: kafkaErr(29),
            },
        ]
        s.batches = [
            [await f.logs(plain, 2), await f.logs(json, 1), await f.logs(json, 1)],
            [await f.logs(plain, 1), await f.logs(both, 1)],
        ]
        scenarios.push(finish(s))
    }
    return scenarios
}

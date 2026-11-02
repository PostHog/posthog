import avro from 'avsc'
import { readFileSync } from 'fs'
import { join } from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { INTERNAL_LOGS_HEADER, signInternalLogs } from '../internal-logs'
import { encodeLogRecords } from '../log-record-avro'
import type { ParityHeader, ParityMessage, ParityScenario, ParityTeam } from './parity-types'

/**
 * Builds the parity corpus. Run only in record mode: the fixture files on disk are the contract,
 * and the Rust crate replays them without this generator. Everything here is seeded, so a re-record
 * on unchanged code writes the same inputs.
 */

const NOW_MS = Date.UTC(2025, 0, 15, 12, 0, 0)
const NOW_MICROS = NOW_MS * 1000
const DAY_MICROS = 86_400_000_000
const SIGNING_KEY = 'parity-signing-key'

function loadSchema(name: 'logs' | 'traces'): avro.Type {
    const raw = readFileSync(join(__dirname, 'fixtures', 'schemas', `${name}.avsc.json`), 'utf8')
    return avro.Type.forSchema(parseJSON(raw))
}

/** mulberry32 — small, seedable, and good enough to spread inputs across code paths. */
class Rng {
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

const TEAMS: ParityTeam[] = [
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

function jsonAttr(value: unknown): string {
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

function makeLogRecord(rng: Rng, i: number, overrides: Rec = {}): Rec {
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
        bytes_uncompressed: null,
        retention_days: null,
        pattern: null,
        pattern_version: null,
        ...overrides,
    }
}

function makeSpanRecord(rng: Rng, i: number): Rec {
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
        bytes_uncompressed: null,
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
    omitSizeHeaders?: boolean
    codec?: 'zstandard' | 'null' | 'deflate'
    schema?: 'logs' | 'traces'
    rawValue?: Buffer | null
}

class MessageFactory {
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
            headers.created_at = new Date(NOW_MS - 1000).toISOString()
        }
        Object.assign(headers, options.headers ?? {})
        const headerList: ParityHeader[] = Object.entries(headers)
        const partition = this.rng.int(4)
        return {
            topic: this.topic,
            partition,
            offset: this.offset++,
            timestamp: NOW_MS - 1000,
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

function baseScenario(name: string, description: string): ParityScenario {
    return {
        name,
        description,
        consumer: 'logs',
        now_ms: NOW_MS,
        config: {},
        teams: TEAMS,
        quota_limited_tokens: [],
        sampling_rules: {},
        retention_rules: {},
        metric_rules: {},
        pattern_message_keys: {},
        traces_retention_days: {},
        team_lookup_faults: {},
        produce_faults: [],
        batches: [],
    }
}

const leaf = (key: string, operator: string, value: unknown, type = 'log_attribute'): Rec => ({
    key,
    operator,
    value,
    type,
})
const group = (type: 'AND' | 'OR', ...values: Rec[]): Rec => ({ type: 'AND', values: [{ type, values }] })

export async function buildParityScenarios(): Promise<ParityScenario[]> {
    const scenarios: ParityScenario[] = []
    const [plain, json, pii, both, attr, ret7] = TEAMS

    {
        const rng = new Rng(1)
        const f = new MessageFactory(rng)
        const s = baseScenario('passthrough', 'No settings or rules: every message is forwarded byte for byte.')
        s.batches = [[await f.logs(plain, 3), await f.logs(plain, 1), await f.logs(ret7, 2)]]
        scenarios.push(s)
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
        scenarios.push(s)
    }
    {
        const rng = new Rng(3)
        const f = new MessageFactory(rng)
        const s = baseScenario('json-attribute', 'Selected-attribute JSON parsing, sniffing and extraction gates.')
        s.config = {
            LOGS_JSON_ATTRIBUTE_PARSING_ENABLED_TEAMS: '105',
            LOGS_JSON_ATTRIBUTE_EXTRACTION_ENABLED_TEAMS: '105',
        }
        const payloads = [
            jsonAttr({ user: { id: 1, email: 'e@example.com' }, list: [1, 2, 3], ok: true }),
            jsonAttr(JSON.stringify({ double: 'encoded', n: 2 })),
            jsonAttr('not an object'),
            jsonAttr([1, 2]),
            '{"raw": "object", "x": 1}',
            jsonAttr(Object.fromEntries(Array.from({ length: 60 }, (_, i) => [`f${i}`, i]))),
            'garbage{',
        ]
        const batch: ParityMessage[] = []
        for (const payload of payloads) {
            const record = makeLogRecord(rng, batch.length, { attributes: { payload, keep: jsonAttr('me') } })
            batch.push(await f.make(attr, [record]))
        }
        s.batches = [batch]
        scenarios.push(s)
    }
    {
        const rng = new Rng(4)
        const f = new MessageFactory(rng)
        const s = baseScenario(
            'parse-failures',
            'Missing token, unknown team, bad size headers, broken avro, null value.'
        )
        s.team_lookup_faults = {
            phc_lookup_error: { name: 'Error', message: 'lookup exploded', dependency_unavailable: false },
        }
        s.batches = [
            [
                await f.logs(plain, 1, { headers: { token: '' } }),
                await f.logs('phc_unknown_token', 1),
                await f.logs('phc_lookup_error', 1),
                await f.logs(plain, 1, { headers: { bytes_uncompressed: '-5' } }),
                await f.logs(plain, 1, { headers: { record_count: 'abc' } }),
                await f.logs(plain, 1, { headers: { bytes_compressed: '12abc' } }),
                await f.logs(plain, 1, { omitSizeHeaders: true }),
                await f.make(plain, [], { rawValue: Buffer.from('not avro at all') }),
                await f.make(json, [], { rawValue: Buffer.from('not avro at all') }),
                await f.make(plain, [], { rawValue: null }),
                await f.make(json, []),
                await f.logs(json, 2, { headers: { min_timestamp: 'garbage' } }),
            ],
        ]
        scenarios.push(s)
    }
    {
        const rng = new Rng(5)
        const f = new MessageFactory(rng)
        const s = baseScenario('gates', 'Backfill gate, quota limits and the per-team rate limiter over two batches.')
        s.config = {
            LOGS_BACKFILL_ENABLED_TEAMS: '102',
            LOGS_LIMITER_BUCKET_SIZE_KB: 1,
            LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND: 1,
            LOGS_LIMITER_TEAM_BUCKET_SIZE_KB: '104:100000',
            LOGS_LIMITER_DISABLED_FOR_TEAMS: '106',
        }
        s.quota_limited_tokens = [pii.api_token]
        s.batches = [
            [
                await f.logs(plain, 2, { headers: { backfill_days: '3' } }),
                await f.logs(json, 2, { headers: { backfill_days: '3' } }),
                await f.logs(pii, 2),
                await f.logs(plain, 3),
                await f.logs(plain, 3),
                await f.logs(both, 3),
                await f.logs(ret7, 3),
                await f.logs(ret7, 3),
            ],
            [await f.logs(plain, 3), await f.logs(both, 3), await f.logs(ret7, 1)],
        ]
        scenarios.push(s)
    }
    {
        const rng = new Rng(6)
        const f = new MessageFactory(rng)
        const s = baseScenario('sampling', 'Severity sampling, path drops, attribute filters, rate-limit rules.')
        s.config = { LOGS_SAMPLING_ENABLED_TEAMS: '101,102,104', LOGS_BILLING_PRORATE_ENABLED: true }
        s.sampling_rules = {
            101: [
                {
                    id: 'sev-drop-debug',
                    rule_type: 'severity_sampling',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        actions: {
                            DEBUG: { type: 'drop' },
                            INFO: { type: 'sample', rate: 0.5 },
                            WARN: { type: 'keep' },
                            ERROR: { type: 'keep' },
                        },
                    },
                },
                {
                    id: 'path-healthz',
                    rule_type: 'path_drop',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { patterns: ['/healthz', '^/internal/.*'] },
                },
            ],
            102: [
                {
                    id: 'attr-filter-drop',
                    rule_type: 'path_drop',
                    scope_service: 'api',
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: {
                        patterns: ['GET'],
                        match_attribute_key: 'http.method',
                        filter_group: group(
                            'OR',
                            leaf('user.email', 'icontains', 'EXAMPLE.COM'),
                            leaf('count', 'gt', 10),
                            leaf('message', 'regex', 'healthz|token=', 'log')
                        ),
                    },
                },
            ],
            104: [
                {
                    id: 'rate-limit-records',
                    rule_type: 'rate_limit',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { logs_per_second: 2, burst_logs: 3 },
                },
            ],
        }
        const batch: ParityMessage[] = []
        for (const team of [plain, json, both]) {
            for (let m = 0; m < 6; m++) {
                batch.push(await f.logs(team, 1 + rng.int(6)))
            }
        }
        // A message where every record is dropped, so the whole message is suppressed.
        batch.push(await f.logs(plain, 3, {}, { severity_text: 'DEBUG', severity_number: 5, attributes: null }))
        s.batches = [batch]
        scenarios.push(s)
    }
    {
        const rng = new Rng(7)
        const f = new MessageFactory(rng)
        const s = baseScenario('retention', 'Per-row retention rules and expired-row drops from backdated imports.')
        s.config = {
            LOGS_RETENTION_ENABLED_TEAMS: '*',
            LOGS_BACKFILL_ENABLED_TEAMS: '*',
            LOGS_BILLING_PRORATE_ENABLED: true,
        }
        s.retention_rules = {
            101: {
                logs: [
                    {
                        id: 'ret-errors-90',
                        config: {
                            retention_days: 90,
                            filter_group: group('AND', leaf('severity_text', 'exact', ['ERROR'], 'log')),
                        },
                    },
                    {
                        id: 'ret-worker-7',
                        config: {
                            retention_days: 7,
                            filter_group: group('AND', leaf('service_name', 'exact', 'worker')),
                        },
                    },
                    { id: 'ret-invalid', config: { retention_days: 'forever' } },
                ],
            },
        }
        const old = (days: number) => NOW_MICROS - days * DAY_MICROS
        const batch: ParityMessage[] = []
        for (const team of [plain, ret7, both]) {
            const records = [
                makeLogRecord(rng, 1, { timestamp: old(1) }),
                makeLogRecord(rng, 2, { timestamp: old(10), severity_text: 'ERROR' }),
                makeLogRecord(rng, 3, { timestamp: old(10), service_name: 'worker' }),
                makeLogRecord(rng, 4, { timestamp: old(40) }),
                makeLogRecord(rng, 5, { timestamp: null }),
            ]
            batch.push(
                await f.make(team, records, { headers: { min_timestamp: String(old(40)), backfill_days: '40' } })
            )
            batch.push(await f.make(team, records.slice(3, 4), { headers: { min_timestamp: String(old(40)) } }))
            batch.push(await f.make(team, records.slice(0, 1), { headers: { min_timestamp: String(old(1)) } }))
        }
        s.batches = [batch]
        scenarios.push(s)
    }
    {
        const rng = new Rng(8)
        const f = new MessageFactory(rng)
        const s = baseScenario('pattern-masking', 'Pattern masking with default and team-configured message keys.')
        s.config = { LOGS_PATTERN_MASKING_ENABLED_TEAMS: '101,102' }
        s.pattern_message_keys = { 102: ['msg', 'message', 'event'] }
        const batch: ParityMessage[] = []
        for (const team of [plain, json, pii]) {
            for (let i = 0; i < 6; i++) {
                batch.push(await f.logs(team, 4))
            }
        }
        s.batches = [batch]
        scenarios.push(s)
    }
    {
        const rng = new Rng(9)
        const f = new MessageFactory(rng)
        const s = baseScenario('metric-rules', 'Team metric rules plus the built-in default rules.')
        s.config = { LOGS_METRICS_RULES_ENABLED_TEAMS: '101,102', LOGS_DEFAULT_METRIC_RULES_ENABLED_TEAMS: '102' }
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
        }
        const batch: ParityMessage[] = []
        for (const team of [plain, json, both]) {
            for (let i = 0; i < 5; i++) {
                batch.push(await f.logs(team, 1 + rng.int(5)))
            }
        }
        s.batches = [batch]
        scenarios.push(s)
    }
    {
        const rng = new Rng(10)
        const f = new MessageFactory(rng)
        const s = baseScenario('internal-logs', 'Signed internal batches: unbilled, wrong team, stale and forged.')
        s.config = {
            LOGS_INTERNAL_INGESTION_SIGNING_KEYS: SIGNING_KEY,
            LOGS_INTERNAL_INGESTION_ENABLED_TEAMS: '101,102',
            LOGS_SAMPLING_ENABLED_TEAMS: '*',
        }
        s.sampling_rules = {
            101: [
                {
                    id: 'drop-all-debug',
                    rule_type: 'severity_sampling',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { actions: { DEBUG: { type: 'drop' } } },
                },
            ],
        }
        const signedAt = new Date(NOW_MS - 2000)
        const created = new Date(NOW_MS - 1000).toISOString()
        const sign = (source: string, teamId: number, at = signedAt) =>
            signInternalLogs(SIGNING_KEY, source, teamId, at)
        s.batches = [
            [
                await f.logs(plain, 3, {
                    headers: { [INTERNAL_LOGS_HEADER]: sign('hog_flow', 101), created_at: created },
                }),
                await f.logs(json, 2, {
                    headers: { [INTERNAL_LOGS_HEADER]: sign('hog_flow', 102), created_at: created },
                }),
                await f.logs(both, 2, {
                    headers: { [INTERNAL_LOGS_HEADER]: sign('hog_flow', 104), created_at: created },
                }),
                await f.logs(plain, 2, {
                    headers: { [INTERNAL_LOGS_HEADER]: sign('hog_flow', 102), created_at: created },
                }),
                await f.logs(plain, 2, {
                    headers: {
                        [INTERNAL_LOGS_HEADER]: sign('hog_flow', 101, new Date(NOW_MS - 3_600_000)),
                        created_at: created,
                    },
                }),
                await f.logs(plain, 2, {
                    headers: { [INTERNAL_LOGS_HEADER]: sign('unknown_src', 101), created_at: created },
                }),
                await f.logs(plain, 2, {
                    headers: { [INTERNAL_LOGS_HEADER]: 'v1.hog_flow.1736942398.deadbeef', created_at: created },
                }),
                await f.logs(plain, 2, { headers: { 'internal-source': 'spoofed' } }),
                await f.logs(plain, 2, {
                    headers: {
                        [INTERNAL_LOGS_HEADER]: sign('hog_flow', 101),
                        created_at: created,
                        backfill_days: '2',
                    },
                }),
            ],
        ]
        scenarios.push(s)
    }
    {
        const rng = new Rng(11)
        const f = new MessageFactory(rng)
        const s = baseScenario(
            'faults',
            'Produce failures route to the DLQ; DLQ and dependency outages fail the batch.'
        )
        s.produce_faults = [
            {
                output: 'logs',
                team_id: '102',
                times: 1,
                error: { name: 'MessageSizeTooLarge', message: 'too big', dependency_unavailable: false },
            },
        ]
        s.batches = [[await f.logs(plain, 2), await f.logs(json, 2), await f.logs(json, 1)]]
        scenarios.push(s)

        const s2 = baseScenario('faults-dlq-down', 'A failed DLQ write after a failed produce fails the batch.')
        s2.produce_faults = [
            {
                output: 'logs',
                team_id: '102',
                times: 1,
                error: { name: 'MessageSizeTooLarge', message: 'too big', dependency_unavailable: false },
            },
            {
                output: 'logs_dlq',
                times: 10,
                error: { name: 'KafkaError', message: 'dlq down', dependency_unavailable: false },
            },
        ]
        s2.batches = [[await f.logs(plain, 2), await f.logs(json, 2)], [await f.logs(plain, 1)]]
        scenarios.push(s2)

        const s3 = baseScenario('faults-dependency', 'A dependency outage on produce outlasts the retries.')
        s3.produce_faults = [
            {
                output: 'logs',
                team_id: '101',
                times: 10,
                error: { name: 'Error', message: 'kafka unavailable', dependency_unavailable: true },
            },
        ]
        s3.batches = [[await f.logs(plain, 2), await f.logs(json, 2)], [await f.logs(json, 1)]]
        scenarios.push(s3)

        const s4 = baseScenario('faults-transient', 'A dependency blip shorter than the retries is absorbed.')
        s4.produce_faults = [
            {
                output: 'logs',
                team_id: '101',
                times: 1,
                error: { name: 'Error', message: 'blip', dependency_unavailable: true },
            },
        ]
        s4.batches = [[await f.logs(plain, 2)]]
        scenarios.push(s4)
    }
    {
        const rng = new Rng(12)
        const f = new MessageFactory(rng, 'traces_ingestion')
        const s = baseScenario('traces', 'The traces consumer: spans schema, spans retention and metric rules.')
        s.consumer = 'traces'
        s.config = {
            TRACES_RETENTION_ENABLED_TEAMS: '101',
            TRACES_METRICS_RULES_ENABLED_TEAMS: '101',
            LOGS_PATTERN_MASKING_ENABLED_TEAMS: '*',
        }
        s.traces_retention_days = { 101: 30, 102: 14 }
        s.retention_rules = {
            101: {
                spans: [
                    {
                        id: 'span-ret',
                        config: {
                            retention_days: 60,
                            filter_group: group('AND', leaf('name', 'exact', 'job', 'span_attribute')),
                        },
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
                    group_by: ['service_name', 'name'],
                    source: 'spans',
                },
            ],
        }
        const batch: ParityMessage[] = []
        for (const team of [plain, json, pii]) {
            const records = Array.from({ length: 4 }, (_, i) => makeSpanRecord(rng, batch.length * 10 + i))
            batch.push(await f.make(team, records, { schema: 'traces' }))
        }
        s.batches = [batch]
        scenarios.push(s)
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
        scenarios.push(s)
    }
    {
        const rng = new Rng(14)
        const f = new MessageFactory(rng)
        const s = baseScenario('fuzz', 'Seeded random mix of every feature, for coverage the hand cases miss.')
        s.config = {
            LOGS_SAMPLING_ENABLED_TEAMS: '*',
            LOGS_RETENTION_ENABLED_TEAMS: '*',
            LOGS_PATTERN_MASKING_ENABLED_TEAMS: '*',
            LOGS_METRICS_RULES_ENABLED_TEAMS: '*',
            LOGS_DEFAULT_METRIC_RULES_ENABLED_TEAMS: '101,103',
            LOGS_JSON_ATTRIBUTE_PARSING_ENABLED_TEAMS: '*',
            LOGS_JSON_ATTRIBUTE_EXTRACTION_ENABLED_TEAMS: '*',
            LOGS_BACKFILL_ENABLED_TEAMS: '101,104',
            LOGS_BILLING_PRORATE_ENABLED: true,
        }
        s.quota_limited_tokens = [TEAMS[5].api_token]
        s.sampling_rules = {
            102: [
                {
                    id: 'fuzz-sev',
                    rule_type: 'severity_sampling',
                    scope_service: 'web',
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { actions: { DEBUG: { type: 'drop' }, INFO: { type: 'sample', rate: 0.3 } } },
                },
            ],
            104: [
                {
                    id: 'fuzz-path',
                    rule_type: 'path_drop',
                    scope_service: null,
                    scope_path_pattern: null,
                    scope_attribute_filters: [],
                    config: { patterns: ['/api/v1'], match_attribute_key: 'url.path' },
                },
            ],
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
        s.metric_rules = {
            102: [
                {
                    id: 'fuzz-metric',
                    metric_name: 'by_level',
                    filter_group: group(
                        'OR',
                        leaf('level', 'exact', 'error'),
                        leaf('severity_text', 'exact', 'WARN', 'log')
                    ),
                    value_attribute: 'count',
                    group_by: ['severity_text', 'resource_attributes.k8s.pod.name'],
                },
            ],
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
        scenarios.push(s)
    }
    return scenarios
}

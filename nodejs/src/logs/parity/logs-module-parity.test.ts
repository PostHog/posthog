import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'fs'
import { join } from 'path'

import { compileHog } from '~/cdp/templates/compiler'
import { parseJSON } from '~/common/utils/json-parse'

import { decodeLogAttributeValue, encodeLogAttributeValue } from '../attribute-value'
import { InternalLogsVerifier, signInternalLogs } from '../internal-logs'
import { parseLogBodyForIngestion } from '../log-body-parse'
import { MESSAGE_KEYS, buildLogPattern } from '../log-pattern-mask'
import { scrubPlainStringWithStats } from '../log-pii-scrub'
import { type LogRecord, transformDecodedLogRecordsInPlace } from '../log-record-avro'
import { type MetricRuleRow, compileMetricRules } from '../metrics-rules/compile-metric-rules'
import { withDefaultMetricRules } from '../metrics-rules/default-metric-rules'
import { buildMetricRulesOtlpPayload } from '../metrics-rules/otlp-payload'
import { createBatchTallies, tallyRecords } from '../metrics-rules/tally'
import { measureContentWeights } from '../pipeline/log-processing-pipeline'
import { type RetentionRuleRow, compileRetentionRuleSet } from '../retention/compile-retention-rules'
import { evaluateRetentionDays } from '../retention/evaluate-retention'
import { type SamplingRuleRow, compileRuleSet } from '../sampling/compile-rules'
import { evaluateLogRecord } from '../sampling/evaluate'
import {
    buildLogRecordGlobals,
    executeLogTransformation,
    resolveLogTransformationInputs,
} from '../transformations/hog-log-exec'
import { canonicalizeAvroValue } from './parity-harness'

// Recorded with `LOGS_PARITY_RECORD=1`. Inputs target what a port gets wrong: UTF-16 slicing, key order, number format, `Date.parse`.
const DIR = join(__dirname, 'fixtures', 'modules')
const RECORD = process.env.LOGS_PARITY_RECORD === '1'
const NOW_MS = Date.UTC(2025, 0, 15, 12, 37, 13, 250)

type Case = { input: unknown; output: unknown }

const STRINGS: string[] = [
    '',
    'plain text',
    'user alice@example.com logged in from 192.168.1.20 and 2001:db8::1',
    'card 4111 1111 1111 1111 exp 12/29, 4111-1111-1111-1111, 5500000000000004',
    'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789 token=sk_live_FAKEFAKEFAKE1234 password=hunter2',
    'phone +1 (555) 123-4567 ssn 123-45-6789 iban GB82WEST12345698765432',
    'aws AKIAIOSFODNN7EXAMPLE jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def456',
    'request 3fa85f64-5717-4562-b3fc-2c963f66afa6 took 12ms on host ip-10-0-0-1 at 2025-01-15T10:00:00.123Z',
    'GET /api/users/12345/orders/987?page=2&token=abc 200 34ms',
    'hex 0xdeadbeef sha 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
    'emoji 🚀🔥✓ and accents héllo wörld and CJK 日本語テキスト',
    '🚀'.repeat(300),
    'é'.repeat(5000),
    'x'.repeat(70_000),
    '  leading and trailing whitespace \t\n',
    'mixed\r\nline\nendings\rhere',
    '{"msg": "json message 123", "level": "info", "user_id": 42}',
    '{"message": {"nested": "object"}, "msg": "fallback 7"}',
    '{"event": "user.signup", "id": "abc-123"}',
    '{"text": "custom key 99"}',
    '["array", "body", 1, 2]',
    '"a json string 42"',
    '12345.678',
    'null',
    'true',
    '{"a": 1, "1": "int key", "b": {"c": [1, 2, {"d": null}]}, "0": "zero"}',
    '{"big": 12345678901234567890, "small": 1e-7, "neg": -0, "exp": 1e21, "f": 0.30000000000000004, "i": 1.0}',
    '{"__proto__": {"x": 1}, "constructor": "c", "toString": "t", "hasOwnProperty": "h"}',
    '{"dup": 1, "dup": 2}',
    '{"deep": ' + '['.repeat(140) + '1' + ']'.repeat(140) + '}',
    JSON.stringify(Object.fromEntries(Array.from({ length: 70 }, (_, i) => [`k${i}`, i]))),
    JSON.stringify({ arr: Array.from({ length: 80 }, (_, i) => i) }),
    JSON.stringify({ arr: Array.from({ length: 12_000 }, () => 1) }),
    JSON.stringify(Object.fromEntries(Array.from({ length: 60 }, (_, i) => [String(59 - i), i]))),
    JSON.stringify({ 'dotted.key': { nested: 'v' }, dotted: { key: 'collision' } }),
    JSON.stringify({ s: 'escaped \\n newline and "quotes" and \t tabs and \u0000 nul', u: '  ' }),
    JSON.stringify({ long: 'y'.repeat(70_000) }),
    '{not valid json',
    '{"trailing": "comma",}',
    "{'single': 'quotes'}",
    '﻿{"bom": true}',
    '<html><body>error 500 at /checkout</body></html>',
    'ERROR [2025-01-15 10:00:00,123] com.example.Service - failed id=987654 user=bob@example.org',
    '10.0.0.1 - - [15/Jan/2025:10:00:00 +0000] "GET /index.html HTTP/1.1" 200 1043',
]

const DATE_STRINGS: (string | undefined)[] = [
    undefined,
    '',
    '2025-01-15T12:00:00.000Z',
    '2025-01-15T12:00:00Z',
    '2025-01-15T12:00:00.123456Z',
    '2025-01-15T12:00:00+02:00',
    '2025-01-15T12:00:00',
    '2025-01-15 12:00:00',
    '2025-01-15',
    '2025-1-5',
    'Jan 15 2025 12:00:00 GMT',
    'Wed, 15 Jan 2025 12:00:00 GMT',
    '15 January 2025',
    '1736942400',
    '1736942400000',
    'not a date',
    '2025-02-30T00:00:00Z',
    '2025-01-15T25:00:00Z',
    '+002025-01-15T12:00:00Z',
    '  2025-01-15T12:00:00Z  ',
]

const RECORD_BODIES = STRINGS.filter((body) => body.length < 6000)

class Rng {
    constructor(private state: number) {}
    next(): number {
        this.state = (this.state + 0x6d2b79f5) | 0
        let t = this.state
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    int(n: number): number {
        return Math.floor(this.next() * n)
    }
    pick<T>(items: readonly T[]): T {
        return items[this.int(items.length)]
    }
}

const jsonAttr = (value: unknown): string => JSON.stringify(value)

function makeRecord(rng: Rng, i: number): LogRecord {
    const attributes: Record<string, string> = {}
    for (let a = 0; a < rng.int(7); a++) {
        attributes[rng.pick(['http.method', 'url.path', 'user.email', 'count', 'payload', 'k', '1', 'level', 'ms'])] =
            rng.pick([
                jsonAttr('GET'),
                jsonAttr('/healthz'),
                jsonAttr('/api/v1/items'),
                jsonAttr('carol@example.com'),
                jsonAttr(42),
                jsonAttr(-3.5),
                jsonAttr('12.5'),
                jsonAttr(true),
                jsonAttr({ nested: { json: 'payload', n: 1 } }),
                jsonAttr(JSON.stringify({ stringified: 'json', arr: [1, 2] })),
                'raw-unquoted',
                jsonAttr('🚀'.repeat(200)),
                jsonAttr(''),
            ])
    }
    return {
        uuid: `uuid-${i}`,
        trace_id: Buffer.from(Array.from({ length: 16 }, () => rng.int(256))),
        span_id: rng.int(2) ? Buffer.from(Array.from({ length: 8 }, () => rng.int(256))) : null,
        trace_flags: null,
        timestamp: rng.int(4) === 0 ? null : (NOW_MS - rng.int(30 * 60 * 1000)) * 1000,
        observed_timestamp: NOW_MS * 1000,
        // Oversized bodies stay in the string vectors and two normalize cases, which keeps these files small.
        body: rng.pick(RECORD_BODIES),
        severity_text: rng.pick(['DEBUG', 'INFO', 'WARN', 'ERROR', 'info', 'warning', 'fatal', 'trace', '', null]),
        severity_number: rng.pick([1, 5, 9, 13, 17, 21, 0, null]),
        service_name: rng.pick(['api', 'worker', 'web', null]),
        resource_attributes: rng.int(5)
            ? { 'service.name': jsonAttr(rng.pick(['api', 'worker'])), 'k8s.pod.name': jsonAttr(`pod-${rng.int(3)}`) }
            : null,
        instrumentation_scope: rng.pick([null, 'scope@1.0']),
        event_name: rng.pick([null, 'request']),
        attributes: rng.int(10) ? attributes : null,
        bytes_uncompressed: rng.int(4) ? 50 + rng.int(800) : null,
    }
}

/** The JSON form of a record in the vectors: bytes as `{ $bytes: hex }`, map key order kept. */
function recordToJson(record: LogRecord): unknown {
    return Object.fromEntries(
        Object.entries(record).map(([key, value]) => [
            key,
            Buffer.isBuffer(value) ? { $bytes: value.toString('hex') } : value,
        ])
    )
}

const leaf = (key: string, operator: string, value: unknown, type = 'log_attribute') => ({ key, operator, value, type })
const group = (type: 'AND' | 'OR', ...values: unknown[]) => ({ type: 'AND', values: [{ type, values }] })

const FILTER_GROUPS: unknown[] = [
    null,
    { type: 'XOR', values: [] },
    group('AND', leaf('severity_text', 'exact', 'ERROR', 'log')),
    group('AND', leaf('severity_level', 'exact', ['error', 'ERROR'])),
    group('OR', leaf('user.email', 'icontains', 'EXAMPLE.COM'), leaf('count', 'gt', 10)),
    group('AND', leaf('count', 'lte', '42'), leaf('count', 'gte', 42)),
    group('AND', leaf('message', 'regex', '^(GET|POST) /api', 'log')),
    group('AND', leaf('message', 'not_regex', '(?=lookahead)', 'log')),
    group('AND', leaf('message', 'regex', 'HEALTHZ|token=', 'log')),
    group('AND', leaf('url.path', 'starts_with', '/api'), leaf('http.method', 'is_not', 'POST')),
    group('AND', leaf('url.path', 'ends_with', 'z')),
    group('AND', leaf('k', 'is_set', null)),
    group('AND', leaf('k', 'is_not_set', null)),
    group('AND', leaf('service.name', 'exact', 'worker', 'log_resource_attribute')),
    group('AND', leaf('service_name', 'in', ['api', 'web'])),
    group('AND', leaf('k8s.pod.name', 'not_in', ['pod-0'], 'log_resource_attribute')),
    group('AND', leaf('payload', 'not_icontains', 'json')),
    group('AND', leaf('ms', 'unknown_operator', 'x')),
    group(
        'OR',
        group('AND', leaf('level', 'exact', 'info'), leaf('count', 'lt', 50)),
        leaf('1', 'exact', 'raw-unquoted')
    ),
]

type HogTransformCase = {
    hog: string
    record?: Partial<LogRecord>
    inputs?: Record<string, unknown>
    sensitive?: string[]
}

const HOG_PROJECT = { id: 7, name: '', url: 'http://localhost:8010/project/7' }

const hogRecord = (overrides: Partial<LogRecord> = {}): LogRecord => ({
    uuid: '0197a3f2-1111-7000-8000-000000000001',
    trace_id: Buffer.from('0123456789abcdef0123456789abcdef', 'hex'),
    span_id: Buffer.from(Buffer.from('0123456789abcdef', 'hex').toString('base64')),
    trace_flags: 0,
    timestamp: 1_736_944_633_250_123,
    observed_timestamp: 1_736_944_633_250_000,
    body: 'user jane@example.com logged in',
    severity_text: 'info',
    severity_number: 9,
    service_name: 'auth-api',
    resource_attributes: { 'k8s.namespace.name': '"auth"' },
    instrumentation_scope: 'auth.sessions',
    event_name: null,
    attributes: { 'http.method': '"POST"', user_email: '"jane@example.com"', '10': '"ten"', '2': '2', b: 'raw' },
    bytes_uncompressed: 120,
    ...overrides,
})

const doubled = (times: number): string =>
    `let s := 'xxxxxxxxxxxxxxxx'\nfor (let i := 0; i < ${times}; i := i + 1) {\n    s := concat(s, s)\n}`

// The wall-clock timeout and budgets are left out: they depend on the machine, so the Rust tests pin them separately.
const HOG_TRANSFORM_CASES: HogTransformCase[] = [
    {
        hog: `let rec := record\nrec.body := replaceAll(rec.body, 'jane@example.com', '[REDACTED]')\nrec.attributes.user_email := sha256Hex(rec.attributes.user_email)\nreturn rec`,
    },
    { hog: `let rec := record\nrec.attributes.tagged := inputs.tag\nreturn rec`, inputs: { tag: 'from-input' } },
    { hog: `if (record.attributes['http.method'] == 'POST') {\n    return null\n}\nreturn record` },
    { hog: `return false` },
    { hog: `return true` },
    { hog: `return 'nope'` },
    { hog: `return 42` },
    { hog: `return [1, 2]` },
    { hog: `return (1, 2)` },
    { hog: `let rec := record\nrec.body := 42\nreturn rec` },
    { hog: `let rec := record\nrec.severity_text := {'a': 1}\nreturn rec` },
    { hog: `let rec := record\nrec.attributes := [1, 2]\nreturn rec` },
    {
        hog: `let rec := record\nrec.service_name := 'spoofed'\nrec.timestamp := 1\nrec.trace_id := 'x'\nrec.body := 'changed'\nreturn rec`,
    },
    { hog: `return {'body': 'only the body'}` },
    { hog: `return {'body': null, 'severity_text': null}` },
    { hog: `return {'attributes': null, 'resource_attributes': null}` },
    { hog: `return {'attributes': {}}` },
    { hog: `return record` },
    { hog: `let rec := record\nrec.attributes.retry_count := 3\nrec.attributes.user_email := null\nreturn rec` },
    {
        hog: `let rec := record\nrec.attributes.obj := {'b': 1, 'a': [1, 2.5, null, true], '1': 'x'}\nrec.attributes.f := 0.1 + 0.2\nrec.attributes.big := 1e21\nrec.attributes.neg := -0.0\nreturn rec`,
    },
    {
        hog: `let rec := record\nrec.attributes['5'] := 'five'\nrec.attributes.z := 'z'\nrec.attributes.a := 'a'\nrec.resource_attributes['0'] := 'zero'\nreturn rec`,
    },
    {
        hog: `let rec := record\nlet names := []\nfor (let k, v in record.attributes) {\n    names := arrayPushBack(names, k)\n}\nrec.body := arrayStringConcat(names, ',')\nrec.attributes.keys := keys(record.attributes)\nreturn rec`,
    },
    {
        hog: `let rec := record\nrec.attributes.half := record.severity_number / 2\nrec.attributes.times := record.severity_number * 2\nrec.attributes.text := toString(record.severity_number)\nrec.attributes.fmt := f'{record.severity_number}'\nrec.attributes.ms := record.timestamp / 1000\nrec.attributes.mod := record.timestamp % 1000\nrec.attributes.huge := record.timestamp * 10000000\nreturn rec`,
    },
    {
        hog: `let rec := record\nrec.attributes.r := inputs.ratio * 2\nrec.attributes.w := inputs.whole / 2\nrec.attributes.s := concat('n=', inputs.whole)\nrec.attributes.e := inputs.whole == 3\nrec.attributes.l := inputs.list\nrec.attributes.int := toInt(inputs.ratio)\nreturn rec`,
        inputs: { ratio: 1.5, whole: 3, list: [1, 2.5, 'x', { k: null }] },
    },
    {
        hog: `let rec := record\nrec.body := concat(record.trace_id, '/', record.span_id, '/', project.url, '/', toString(project.id))\nrec.attributes.scope := record.instrumentation_scope\nrec.attributes.event := record.event_name\nreturn rec`,
    },
    {
        hog: `let rec := record\nrec.body := f'key: {inputs.apiKey}'\nrec.attributes[inputs.apiKey] := 'anything'\nrec.attributes.nested := {'secret': inputs.apiKey}\nreturn rec`,
        inputs: { apiKey: 'super-secret-key' },
        sensitive: ['super-secret-key'],
    },
    {
        hog: `for (let i := 0; i < 10; i := i + 1) {\n    print('iteration', i, 'secret-value')\n}\nreturn record`,
        sensitive: ['secret-value'],
    },
    { hog: `print({'a': 1, 'b': [1, 2.5, null]}, null, 3, 4.5, true, 'é🚀', (1, 2))\nreturn record` },
    {
        hog: `print('about to explode', inputs.apiKey)\nthrow Error('boom')`,
        inputs: { apiKey: 'k-123' },
        sensitive: ['k-123'],
    },
    { hog: `let rec := record\nrec.attributes.self := rec.attributes\nreturn rec`, sensitive: ['some-secret'] },
    { hog: `let rec := record\nrec.attributes.self := rec.attributes\nreturn rec` },
    { hog: `let rec := record\nrec.other := rec\nreturn rec` },
    { hog: `${doubled(17)}\nlet rec := record\nrec.body := s\nreturn rec` },
    {
        hog: `${doubled(15)}\nlet rec := record\nrec.body := s\nrec.severity_text := s\nrec.attributes.padding := s\nreturn rec`,
    },
    {
        hog: `${doubled(15)}\nreturn {'body': s}`,
        record: { attributes: { big: JSON.stringify('y'.repeat(600 * 1024)) } },
    },
    { hog: `${doubled(30)}\nreturn record` },
    {
        hog: `return record`,
        record: { attributes: { str_num: '"3"', real_num: '3', flag: 'true', keep: '"plain"', esc: '"a\\"b"' } },
    },
    { hog: `let rec := record\nrec.attributes.str_num := '3'\nreturn rec`, record: { attributes: { str_num: '"3"' } } },
    {
        hog: `let rec := record\nrec.attributes.added := 'x'\nreturn rec`,
        record: { attributes: null, resource_attributes: null, body: null, trace_id: Buffer.alloc(16), span_id: null },
    },
    { hog: `return record.missing.deeply` },
    { hog: `let rec := record\nrec.body := upper(rec.body)\nreturn rec`, record: { body: 'héllo wörld 🚀 ✓' } },
]

async function buildHogTransformCases(): Promise<Case[]> {
    const cases: Case[] = []
    for (const c of HOG_TRANSFORM_CASES) {
        const bytecode = await compileHog(c.hog)
        const record = hogRecord(c.record)
        const input = {
            hog: c.hog,
            bytecode,
            record: recordToJson(record),
            inputs: c.inputs ?? {},
            sensitive: c.sensitive ?? [],
        }
        const outcome = executeLogTransformation(
            bytecode,
            record,
            buildLogRecordGlobals(record, HOG_PROJECT, c.inputs ?? {}),
            {
                timeoutMs: 5000,
                sensitiveValues: c.sensitive,
            }
        )
        cases.push({
            input,
            output: {
                status: outcome.status,
                error: outcome.status === 'failed' ? outcome.error : null,
                logs: outcome.logs,
                record: recordToJson(record),
            },
        })
    }
    return cases
}

// Input templates resolve in declared order and see the inputs resolved before them.
async function buildHogInputsCases(): Promise<Case[]> {
    const templates: [string, Record<string, unknown>][] = [
        [
            'templates in order',
            {
                second: { value: '', bytecode: await compileHog(`return f'{inputs.first}-2'`), order: 1 },
                first: { value: '', bytecode: await compileHog(`return f'{record.service_name}-1'`), order: 0 },
                plain: { value: { n: 3, list: [1, 2.5] } },
                skipped: { value: 'kept as is', bytecode: await compileHog(`return 'not run'`), templating: 'liquid' },
            },
        ],
        [
            'object result',
            { obj: { value: '', bytecode: await compileHog(`return {'k': 'v', 'list': [1, 2], '1': 'i'}`) } },
        ],
        ['numbers', { n: { value: '', bytecode: await compileHog(`return record.severity_number / 2`) } }],
        ['failing template', { bad: { value: '', bytecode: await compileHog(`throw Error('template boom')`) } }],
    ]
    const cases: Case[] = []
    for (const [name, inputs] of templates) {
        const record = hogRecord()
        const globals = buildLogRecordGlobals(record, HOG_PROJECT, {})
        let output: unknown
        try {
            output = {
                inputs: resolveLogTransformationInputs({ inputs, encrypted_inputs: null } as any, globals, 5000).inputs,
            }
        } catch (error) {
            output = { error: String(error) }
        }
        cases.push({ input: { name, inputs, record: recordToJson(record) }, output })
    }
    return cases
}

async function buildAllCases(): Promise<Record<string, Case[]>> {
    const cases = buildCases()
    await settleNormalize(cases)
    cases.hog_transform = await buildHogTransformCases()
    cases.hog_inputs = await buildHogInputsCases()
    return cases
}

function buildCases(): Record<string, Case[]> {
    const rng = new Rng(42)
    const records = Array.from({ length: 160 }, (_, i) => makeRecord(rng, i))
    const out: Record<string, Case[]> = {}

    out.body_parse = STRINGS.map((body) => ({ input: body, output: parseLogBodyForIngestion(body) }))
    out.pii_scrub = STRINGS.map((input) => ({ input, output: scrubPlainStringWithStats(input) }))
    out.attribute_value = [...STRINGS, ...records.flatMap((r) => Object.values(r.attributes ?? {}))].map((input) => ({
        input,
        output: { decoded: decodeLogAttributeValue(input), encoded: encodeLogAttributeValue(input) },
    }))
    out.pattern = [MESSAGE_KEYS, ['text', 'nope'], []].flatMap((keys) =>
        STRINGS.map((body) => ({ input: { body, keys }, output: buildLogPattern(body, keys) }))
    )
    out.date_parse = DATE_STRINGS.map((input) => ({ input: input ?? null, output: Date.parse(input ?? '') }))

    const settingsVariants = [
        { json_parse_logs: true },
        { pii_scrub_logs: true },
        { json_parse_logs: true, pii_scrub_logs: true },
        { json_parse_logs_attribute_key: 'payload' },
        { json_parse_logs: true, pii_scrub_logs: true, json_parse_logs_attribute_key: 'payload' },
    ]
    out.normalize = []
    const oversized = STRINGS.filter((body) => body.length >= 6000).map((body, i) => ({ ...records[i], body }))
    for (const settings of settingsVariants.slice(2)) {
        for (const input of oversized) {
            out.normalize.push({
                input: { settings, record: recordToJson(input) },
                output: { ...input, attributes: input.attributes ? { ...input.attributes } : null },
            })
        }
    }
    for (const settings of settingsVariants) {
        for (let i = 0; i < 40; i++) {
            const input = records[(i * 7 + settingsVariants.indexOf(settings)) % records.length]
            const copy: LogRecord = { ...input, attributes: input.attributes ? { ...input.attributes } : null }
            // Synchronous body: the instrumented helpers resolve immediately.
            out.normalize.push({ input: { settings, record: recordToJson(input) }, output: copy })
        }
    }

    const samplingRuleSets: unknown[][] = [
        [
            {
                id: 's1',
                rule_type: 'severity_sampling',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: {
                    actions: {
                        DEBUG: { type: 'drop' },
                        INFO: { type: 'sample', rate: 0.5 },
                        WARN: { type: 'sample', rate: 1.5 },
                    },
                },
            },
        ],
        [
            {
                id: 'p1',
                rule_type: 'path_drop',
                scope_service: 'api',
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: { patterns: ['/healthz', '^/api/v[0-9]+'], match_attribute_key: 'url.path' },
            },
        ],
        [
            {
                id: 'p2',
                rule_type: 'path_drop',
                scope_service: null,
                scope_path_pattern: '/api/*',
                scope_attribute_filters: [],
                config: { patterns: ['GET'], match_attribute_key: 'http.method', filter_group: FILTER_GROUPS[4] },
            },
        ],
        [
            {
                id: 'p3',
                rule_type: 'path_drop',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [{ key: 'level', value: 'info' }],
                config: { patterns: 'notarray' },
            },
        ],
        [
            {
                id: 'k1',
                rule_type: 'severity_sampling',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: {
                    actions: { ERROR: { type: 'drop' } },
                    always_keep: {
                        status_gte: 500,
                        latency_ms_gt: 1000,
                        predicates: [{ key: 'k', op: 'eq', value: 'x' }],
                    },
                },
            },
        ],
        [
            {
                id: 'u1',
                rule_type: 'mystery',
                scope_service: null,
                scope_path_pattern: null,
                scope_attribute_filters: [],
                config: {},
            },
        ],
    ]
    out.sampling_evaluate = samplingRuleSets.flatMap((rows) => {
        const ruleSet = compileRuleSet(rows as SamplingRuleRow[])
        return records.slice(0, 60).map((record) => ({
            input: { rules: rows, record: recordToJson(record) },
            output: evaluateLogRecord(ruleSet, record),
        }))
    })

    out.retention_evaluate = FILTER_GROUPS.flatMap((filterGroup, g) => {
        const rows: RetentionRuleRow[] = [
            { id: `r${g}`, config: { retention_days: 90, filter_group: filterGroup } },
            {
                id: 'fallback',
                config: { retention_days: 30, filter_group: group('AND', leaf('service_name', 'is_set', null)) },
            },
        ]
        const ruleSet = compileRetentionRuleSet(rows)
        return records.slice(0, 25).map((record) => ({
            input: { rules: rows, record: recordToJson(record) },
            output: evaluateRetentionDays(ruleSet, record),
        }))
    })

    const metricRuleSets: MetricRuleRow[][] = [
        [{ id: 'm1', metric_name: 'count_all', filter_group: null, value_attribute: null, group_by: ['service_name'] }],
        [
            {
                id: 'm2',
                metric_name: 'sum_count',
                filter_group: FILTER_GROUPS[4],
                value_attribute: 'count',
                group_by: ['severity_text', 'attributes.http.method', 'resource_attributes.k8s.pod.name'],
            },
        ],
        [
            {
                id: 'm3',
                metric_name: 'hist_ms',
                filter_group: null,
                value_attribute: 'ms',
                group_by: ['attributes.payload'],
            },
        ],
        [
            {
                id: 'm4',
                metric_name: 'bad group',
                filter_group: { type: 'AND', values: 'x' },
                value_attribute: null,
                group_by: 'notarray' as unknown as string[],
            },
        ],
    ]
    out.metric_tally = metricRuleSets.flatMap((rows) =>
        [false, true].map((withDefaults) => {
            let rules = compileMetricRules(rows)
            if (withDefaults) {
                rules = withDefaultMetricRules(rules, 'logs')
            }
            const tallies = createBatchTallies()
            const batch = records.slice(0, 40)
            tallyRecords(rules, batch, tallies, NOW_MS, () => true)
            let overflow = 0
            for (const count of tallies.seriesOverflow.values()) {
                overflow += count
            }
            return {
                input: {
                    rules: rows,
                    with_default_rules: withDefaults,
                    now_ms: NOW_MS,
                    records: batch.map(recordToJson),
                },
                output: {
                    payload: canonicalizeAvroValue(buildMetricRulesOtlpPayload(rules, tallies, NOW_MS)),
                    value_skipped: tallies.valueSkipped,
                    eval_errors: tallies.evalErrors,
                    series_overflow: overflow,
                },
            }
        })
    )

    out.content_weights = [records.slice(0, 10), records.slice(10, 40), records.slice(40, 41)].map((batch) => ({
        input: batch.map(recordToJson),
        output: [...measureContentWeights(batch).values()],
    }))

    const key = 'k1'
    const signedAt = new Date(NOW_MS - 2000)
    const created = new Date(NOW_MS).toISOString()
    const verifier = new InternalLogsVerifier(`${key},k0`, '1,2', {
        hog_flow: { billed: false, teamRules: false, serviceName: 'posthog-internal-workflows' },
        billed_src: { billed: true, teamRules: true, serviceName: 'billed-src' },
    })
    const signatures: [string | undefined, number, string | undefined][] = [
        [undefined, 1, created],
        [signInternalLogs(key, 'hog_flow', 1, signedAt), 1, created],
        [signInternalLogs('k0', 'hog_flow', 1, signedAt), 1, created],
        [signInternalLogs(key, 'hog_flow', 1, signedAt), 3, created],
        [signInternalLogs(key, 'hog_flow', 2, signedAt), 1, created],
        [signInternalLogs(key, 'billed_src', 2, signedAt), 2, created],
        [signInternalLogs(key, 'constructor', 1, signedAt), 1, created],
        [signInternalLogs(key, 'unknown', 1, signedAt), 1, created],
        [signInternalLogs(key, 'hog_flow', 1, new Date(NOW_MS - 301_000)), 1, created],
        [signInternalLogs(key, 'hog_flow', 1, new Date(NOW_MS - 299_000)), 1, created],
        [signInternalLogs(key, 'hog_flow', 1, signedAt), 1, undefined],
        [signInternalLogs(key, 'hog_flow', 1, signedAt), 1, 'Wed, 15 Jan 2025 12:37:13 GMT'],
        ['v1.hog_flow.1736944631.00', 1, created],
        ['v1.HOG.1736944631.00', 1, created],
        ['v1.hog_flow.0123456789.00', 1, created],
        ['garbage', 1, created],
    ]
    // The Rust port has no producer, so the vectors leave out the producer-only `serviceName`.
    out.internal_verify = signatures.map(([signature, teamId, createdAt]) => {
        const { serviceName: _, ...output } = verifier.verify(signature, teamId, createdAt) ?? {}
        return {
            input: { signature: signature ?? null, team_id: teamId, created_at: createdAt ?? null },
            output: Object.keys(output).length > 0 ? output : null,
        }
    })
    return out
}

async function settleNormalize(cases: Record<string, Case[]>): Promise<void> {
    for (const c of cases.normalize) {
        const record = c.output as LogRecord
        const settings = (c.input as { settings: Record<string, unknown> }).settings
        const pii = await transformDecodedLogRecordsInPlace([record], settings)
        c.output = { record: recordToJson(record), pii_replacements: pii.piiReplacements }
    }
}

describe('logs ingestion module parity vectors', () => {
    if (RECORD) {
        it('records the vectors', async () => {
            const cases = await buildAllCases()
            rmSync(DIR, { recursive: true, force: true })
            mkdirSync(DIR, { recursive: true })
            for (const [name, list] of Object.entries(cases)) {
                writeFileSync(join(DIR, `${name}.json`), JSON.stringify({ cases: list }, null, 1) + '\n')
            }
        })
        return
    }

    const files = existsSync(DIR) ? readdirSync(DIR).filter((f) => f.endsWith('.json')) : []

    it('has vectors', () => {
        expect(files.length).toBeGreaterThan(0)
    })

    it('matches the recorded vectors', async () => {
        const cases = await buildAllCases()
        for (const file of files) {
            const recorded = parseJSON(readFileSync(join(DIR, file), 'utf8')) as { cases: Case[] }
            const actual = parseJSON(JSON.stringify({ cases: cases[file.replace(/\.json$/, '')] }))
            expect({ file, ...actual }).toStrictEqual({ file, ...recorded })
        }
    })
})

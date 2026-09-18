import avro from 'avsc'

import { parseJSON } from '~/common/utils/json-parse'

import * as logBodyParse from './log-body-parse'
import { PII_REDACTED, encodeAttributeCell } from './log-pii-scrub'
import {
    LogRecord,
    bufferProcessingMode,
    decodeLogRecords,
    encodeLogRecords,
    enrichLogRecordFromJsonAttribute,
    enrichLogRecordWithJsonAttributes,
    extractJsonAttributesFromBody,
    flattenJson,
    logProcessingDurationHistogram,
    logsJsonAttributeSniffCounter,
    logsJsonEnrichmentSkippedCounter,
    processLogMessageBuffer,
    sniffJsonLogAttributes,
    transformDecodedLogRecordsInPlace,
} from './log-record-avro'
import { MAX_LOG_RECORD_BYTES, logRecordSizeBytes } from './log-record-size'

const LOG_RECORD_SCHEMA = avro.parse(`{
"type": "record",
"name": "LogRecord",
"doc": "Schema for a structured log or trace event.",
"fields": [
    {
    "name": "uuid",
    "type": ["null", "string"],
    "doc": "Unique identifier for the log record."
    },
    {
    "name": "trace_id",
    "type": ["null", "bytes"],
    "doc": "Identifier for the trace this log is a part of."
    },
    {
    "name": "span_id",
    "type": ["null", "bytes"],
    "doc": "Identifier for the span within the trace."
    },
    {
    "name": "trace_flags",
    "type": ["null", "int"],
    "doc": "Flags associated with the trace."
    },
    {
    "name": "timestamp",
    "type": ["null", {
        "type": "long",
        "logicalType": "timestamp-micros"
    }],
    "doc": "The primary timestamp of the event, in microseconds since epoch."
    },
    {
    "name": "observed_timestamp",
    "type": ["null", {
        "type": "long",
        "logicalType": "timestamp-micros"
    }],
    "doc": "The timestamp when the event was observed or ingested, in microseconds since epoch."
    },
    {
    "name": "body",
    "type": ["null", "string"],
    "doc": "The main content or message of the log."
    },
    {
    "name": "severity_text",
    "type": ["null", "string"],
    "doc": "Human-readable severity level (e.g., 'INFO', 'ERROR')."
    },
    {
    "name": "severity_number",
    "type": ["null", "int"],
    "doc": "Numeric representation of the severity level."
    },
    {
    "name": "service_name",
    "type": ["null", "string"],
    "doc": "The name of the service that generated the event."
    },
    {
    "name": "resource_attributes",
    "type": ["null", {
        "type": "map",
        "values": "string"
    }],
    "doc": "Attributes describing the resource that produced the log (e.g., host, region)."
    },
    {
    "name": "instrumentation_scope",
    "type": ["null", "string"],
    "doc": "The name of the library or framework that captured the log."
    },
    {
    "name": "event_name",
    "type": ["null", "string"],
    "doc": "The name of a specific event that occurred."
    },
    {
    "name": "attributes",
    "type": ["null", {
        "type": "map",
        "values": "string"
    }],
    "doc": "A map of custom string-valued attributes associated with the log."
    },
    {
    "name": "bytes_uncompressed",
    "type": ["null", "long"],
    "doc": "Logical content size of the row (sum of byte lengths of string/map fields). Used by drop-rule accounting; does not include fixed-width numeric or timestamp fields."
    }
]
}`)

const createRecord = (overrides: Partial<LogRecord> = {}): LogRecord => ({
    uuid: null,
    trace_id: null,
    span_id: null,
    trace_flags: null,
    timestamp: null,
    observed_timestamp: null,
    body: null,
    severity_text: null,
    severity_number: null,
    service_name: null,
    resource_attributes: null,
    instrumentation_scope: null,
    event_name: null,
    attributes: null,
    bytes_uncompressed: null,
    ...overrides,
})

describe('log-record-avro', () => {
    describe('sniffJsonLogAttributes', () => {
        it.each([
            [null, 'missing_key'],
            [{}, 'missing_key'],
            [{ payload: '{}' }, 'missing_key'],
            [{ 'payload.json': '{}' }, 'looks_like_json'],
            [{ 'payload.json': ' \n\t[1]' }, 'looks_like_json'],
            [{ 'payload.json': JSON.stringify('{"nested":true}') }, 'looks_like_json'],
            [{ 'payload.json': JSON.stringify('\n\t [1]') }, 'looks_like_json'],
            [{ 'payload.json': '{not valid JSON' }, 'looks_like_json'],
            [{ 'payload.json': '"ordinary text"' }, 'other'],
            [{ 'payload.json': 'null' }, 'other'],
            [{ 'payload.json': '' }, 'other'],
            [{ 'payload.json': ' '.repeat(64) + '{}' }, 'other'],
        ] as const)('classifies %j as %s without mutating the record', async (attributes, outcome) => {
            logsJsonAttributeSniffCounter.reset()
            const record = Object.freeze({ attributes: attributes && Object.freeze(attributes) })

            sniffJsonLogAttributes([record], 'payload.json', 123)
            sniffJsonLogAttributes([record, record], 'payload.json', 456)

            expect((await logsJsonAttributeSniffCounter.get()).values).toEqual([
                expect.objectContaining({ labels: { team_id: '123', outcome }, value: 1 }),
                expect.objectContaining({ labels: { team_id: '456', outcome }, value: 2 }),
            ])
        })
    })

    describe('flattenJson', () => {
        it.each([
            ['flattens simple object', { a: 'b', c: 'd' }, { a: 'b', c: 'd' }],
            ['flattens nested object', { a: { b: 'c' } }, { 'a.b': 'c' }],
            ['flattens deeply nested object', { a: { b: { c: 'd' } } }, { 'a.b.c': 'd' }],
            ['flattens array', { items: ['a', 'b'] }, { 'items.0': 'a', 'items.1': 'b' }],
            [
                'flattens nested array of objects',
                { items: [{ name: 'a' }, { name: 'b' }] },
                { 'items.0.name': 'a', 'items.1.name': 'b' },
            ],
            ['handles null values', { a: null }, { a: 'null' }],
            ['handles undefined values', { a: undefined }, { a: 'undefined' }],
            ['handles number values', { count: 42 }, { count: 42 }],
            ['handles boolean values', { active: true }, { active: true }],
            [
                'handles mixed types',
                { str: 'hello', num: 123, bool: false, nil: null },
                { str: 'hello', num: 123, bool: false, nil: 'null' },
            ],
            ['handles empty object', {}, {}],
            ['handles empty array', { items: [] }, {}],
            [
                'ignores inherited and non-enumerable properties',
                Object.create({ inherited: true }, { kept: { value: 1, enumerable: true }, hidden: { value: 2 } }),
                { kept: 1 },
            ],
            ['preserves later dotted-key overwrites', { path: { value: 1 }, 'path.value': 2 }, { 'path.value': 2 }],
            ['preserves later nested overwrites', { 'path.value': 1, path: { value: 2 } }, { 'path.value': 2 }],
            ['preserves top-level array indexing', ['a', null, { b: true }], { '0': 'a', '1': 'null', '2.b': true }],
        ])('%s', (_, input, expected) => {
            expect(flattenJson(input)).toEqual(expected)
        })

        it.each([
            [{ 'path.value': 1, filler: 2, path: { value: 3 } }, { 'path.value': 3 }],
            [{ text: 1, '': { '2': 2 } }, { '2': 2 }],
            [{ '-1': 1, '': { '0': 2 } }, { '0': 2 }],
            [{ '2': 1, '': { '1': 2 } }, { '1': 2 }],
            [{ '1': 1, '': { '2': 2 } }, { '1': 1 }],
        ])('preserves ordering and collisions beyond the retained field limit for %j', (input, expected) => {
            expect(flattenJson(input, '', 1)).toEqual(expected)
        })

        it.each([
            ['unicode value at budget', { a: '😀' }, 7, { a: '😀' }],
            ['unicode value over budget', { a: '😀' }, 6, null],
            ['escaped value over budget', { a: '\n' }, 4, null],
            ['cumulative paths over budget', { abc: { def: 1 } }, 9, null],
            ['overwritten value releases budget', { 'a.b': 'long', a: { b: 1 } }, 20, { 'a.b': 1 }],
        ] as const)('%s', (_name, input, maxBytes, expected) => {
            expect(flattenJson(input, '', 50, maxBytes)).toEqual(expected)
        })

        it.each([128, 129, 10_000])('bounds deeply nested input at depth %i', (depth) => {
            const input = parseJSON('{"nested":'.repeat(depth) + '1' + '}'.repeat(depth))
            expect(flattenJson(input)).toEqual(depth <= 128 ? { [Array(depth).fill('nested').join('.')]: 1 } : null)
        })

        it.each([
            Array.from({ length: 10_000 }, () => ({})),
            Object.fromEntries(Array.from({ length: 10_000 }, (_, index) => [`key${index}`, {}])),
        ])('bounds wide containers even when they contain no leaves', (input) => {
            expect(flattenJson(input)).toBeNull()
        })

        it.each([
            ['root', 9_999, false, false],
            ['nested', 9_997, true, false],
            ['nested', 9_998, true, true],
        ] as const)(
            'honors the remaining node budget for %s objects with %i children',
            (_name, count, nested, skipped) => {
                const children = Object.fromEntries(Array.from({ length: count }, (_, index) => [`key${index}`, {}]))
                const input = nested ? { first: true, children } : children

                expect(flattenJson(input)).toEqual(skipped ? null : nested ? { first: true } : {})
            }
        )

        it('stops key inspection when a sub-1 MiB object exceeds the node budget', () => {
            const input = Object.fromEntries(Array.from({ length: 100_000 }, (_, index) => [String(index), 0]))
            expect(Buffer.byteLength(JSON.stringify(input))).toBeLessThan(MAX_LOG_RECORD_BYTES)
            const guardedInput = new Proxy(input, {
                getOwnPropertyDescriptor(target, key) {
                    if (key === '10000') {
                        throw new Error('Inspected a key beyond the node budget')
                    }
                    return Reflect.getOwnPropertyDescriptor(target, key)
                },
            })

            expect(flattenJson(guardedInput)).toBeNull()
        })
    })

    describe('extractJsonAttributesFromBody', () => {
        it('extracts attributes from valid JSON body', () => {
            const body = JSON.stringify({ level: 'info', message: 'test' })
            const result = extractJsonAttributesFromBody(body)

            expect(result).toEqual({ level: '\"info\"', message: '\"test\"' })
        })

        it('correctly types number strings', () => {
            const body = JSON.stringify({ numberString: '2', number: 2 })
            const result = extractJsonAttributesFromBody(body)

            expect(result).toEqual({ numberString: '\"2\"', number: '2' })
        })

        it('returns empty object for invalid JSON', () => {
            const result = extractJsonAttributesFromBody('not json')

            expect(result).toEqual({})
        })

        it('returns empty object for null body', () => {
            const result = extractJsonAttributesFromBody(null)

            expect(result).toEqual({})
        })

        it('limits to 50 attributes', () => {
            const largeObject: Record<string, string> = {}
            for (let i = 0; i < 100; i++) {
                largeObject[`key${i}`] = `value${i}`
            }
            const body = JSON.stringify(largeObject)
            const result = extractJsonAttributesFromBody(body)

            expect(Object.keys(result)).toEqual(Array.from({ length: 50 }, (_, index) => `key${index}`))
        })

        it('flattens nested JSON', () => {
            const body = JSON.stringify({
                user: { id: 123, name: 'test' },
                request: { path: '/api' },
            })
            const result = extractJsonAttributesFromBody(body)

            expect(result).toEqual({
                'user.id': '123',
                'user.name': '\"test\"',
                'request.path': '\"/api\"',
            })
        })

        it('returns empty object for primitive JSON values', () => {
            expect(extractJsonAttributesFromBody('"string"')).toEqual({})
            expect(extractJsonAttributesFromBody('123')).toEqual({})
            expect(extractJsonAttributesFromBody('true')).toEqual({})
            expect(extractJsonAttributesFromBody('null')).toEqual({})
        })
    })

    describe('encodeLogRecords and decodeLogRecords', () => {
        it('round-trips multiple LogRecords', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid-1',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: 1704067200000000,
                    observed_timestamp: 1704067200000000,
                    body: 'Test log message 1',
                    severity_text: 'info',
                    severity_number: 9,
                    service_name: 'test-service',
                    resource_attributes: { 'host.name': 'localhost' },
                    instrumentation_scope: 'test@1.0.0',
                    event_name: null,
                    attributes: { key: 'value1' },
                    bytes_uncompressed: 123,
                },
                {
                    uuid: 'test-uuid-2',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: 1704067200000000,
                    observed_timestamp: 1704067200000000,
                    body: 'Test log message 2',
                    severity_text: 'error',
                    severity_number: 17,
                    service_name: 'test-service',
                    resource_attributes: { 'host.name': 'localhost' },
                    instrumentation_scope: 'test@1.0.0',
                    event_name: null,
                    attributes: { key: 'value2' },
                    bytes_uncompressed: 456,
                },
            ]

            const encoded = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const [_, __, decoded] = await decodeLogRecords(encoded)

            expect(decoded).toEqual(records)
        })

        it('handles single record', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: null,
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
            ]

            const encoded = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const [_, __, decoded] = await decodeLogRecords(encoded)

            expect(decoded).toEqual(records)
        })

        it('preserves bytes_uncompressed across encode/decode', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'with-bytes',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: 'hello world',
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: 789,
                },
            ]

            const encoded = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const [_, __, decoded] = await decodeLogRecords(encoded)

            expect(decoded[0].bytes_uncompressed).toBe(789)
        })

        it('rejects promise for invalid buffer', async () => {
            const invalidBuffer = Buffer.from('not avro data')

            await expect(decodeLogRecords(invalidBuffer)).rejects.toThrow()
        })
    })

    describe('enrichLogRecordWithJsonAttributes', () => {
        beforeEach(() => {
            logsJsonEnrichmentSkippedCounter.reset()
        })

        it.each([-1, 0, 1])('checks merged UTF-8 content at the size boundary (%i bytes)', async (offset) => {
            const record = createRecord({
                body: '{"a":"é"}',
                severity_text: 'info',
                attributes: { existing: 'true' },
                resource_attributes: { padding: '' },
            })
            const extractedBytes = 5
            record.resource_attributes!.padding = 'x'.repeat(
                MAX_LOG_RECORD_BYTES - logRecordSizeBytes(record) - extractedBytes + offset
            )
            const original = structuredClone(record)
            const attributes = record.attributes

            expect(enrichLogRecordWithJsonAttributes(record)).toBe(record)

            if (offset > 0) {
                expect(record).toEqual(original)
                expect(record.attributes).toBe(attributes)
                expect((await logsJsonEnrichmentSkippedCounter.get()).values).toEqual([
                    expect.objectContaining({ labels: { reason: 'output_size', source: 'body' }, value: 1 }),
                ])
            } else {
                expect(record).toEqual({ ...original, attributes: { existing: 'true', a: '"é"' } })
                expect(logRecordSizeBytes(record)).toBe(MAX_LOG_RECORD_BYTES + offset)
                expect((await logsJsonEnrichmentSkippedCounter.get()).values).toEqual([])
            }
        })

        it('counts only the winning sender value toward the merged budget', () => {
            const record = createRecord({
                body: JSON.stringify({ payload: 'x'.repeat(600 * 1024), added: true }),
                attributes: { payload: '"sender"' },
            })
            enrichLogRecordWithJsonAttributes(record)
            expect(record.attributes).toEqual({ payload: '"sender"', added: 'true' })
        })

        it.each([
            ['input_size', JSON.stringify({ value: '😀'.repeat(MAX_LOG_RECORD_BYTES / 4) })],
            ['output_size', JSON.stringify({ value: 'x'.repeat(600 * 1024), other: true })],
            ['flatten_budget', '{"nested":'.repeat(129) + '1' + '}'.repeat(129)],
        ])('preserves records and counts %s skips through the buffer processor', async (reason, body) => {
            const record = createRecord({ body, attributes: { original: 'true' } })
            const encoded = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', [record])
            const result = await processLogMessageBuffer(encoded, { json_parse_logs: true })
            const [, , decoded] = await decodeLogRecords(result.value!)

            expect(decoded).toEqual([{ ...record, bytes_uncompressed: null }])
            expect((await logsJsonEnrichmentSkippedCounter.get()).values).toEqual([
                expect.objectContaining({ labels: { reason, source: 'body' }, value: 1 }),
            ])
        })

        it('does not parse oversized bodies on direct or batch enrichment paths', async () => {
            const body = JSON.stringify({ value: '😀'.repeat(MAX_LOG_RECORD_BYTES / 4) })
            const parse = jest.spyOn(logBodyParse, 'parseLogBodyForIngestion')
            try {
                expect(extractJsonAttributesFromBody(body)).toEqual({})
                enrichLogRecordWithJsonAttributes(createRecord({ body }))
                await transformDecodedLogRecordsInPlace([createRecord({ body })], { json_parse_logs: true })
                expect(parse.mock.calls.every(([input]) => input === null)).toBe(true)
            } finally {
                parse.mockRestore()
            }
        })

        it('adds JSON attributes from body', () => {
            const record: LogRecord = {
                uuid: 'test-uuid',
                trace_id: null,
                span_id: null,
                trace_flags: null,
                timestamp: null,
                observed_timestamp: null,
                body: JSON.stringify({ level: 'info', context: { user_id: 123 } }),
                severity_text: null,
                severity_number: null,
                service_name: null,
                resource_attributes: null,
                instrumentation_scope: null,
                event_name: null,
                attributes: null,
            }

            enrichLogRecordWithJsonAttributes(record)

            expect(record.attributes).toEqual({
                level: '\"info\"',
                'context.user_id': '123',
            })
        })

        it('preserves existing attributes', () => {
            const record: LogRecord = {
                uuid: 'test-uuid',
                trace_id: null,
                span_id: null,
                trace_flags: null,
                timestamp: null,
                observed_timestamp: null,
                body: JSON.stringify({ level: 'info', message: 'test' }),
                severity_text: null,
                severity_number: null,
                service_name: null,
                resource_attributes: null,
                instrumentation_scope: null,
                event_name: null,
                attributes: { level: '\"error\"', existing: '\"attribute\"' },
            }

            enrichLogRecordWithJsonAttributes(record)

            expect(record.attributes).toEqual({
                level: '\"error\"',
                existing: '\"attribute\"',
                message: '\"test\"',
            })
        })

        it('does nothing for null body', () => {
            const record: LogRecord = {
                uuid: 'test-uuid',
                trace_id: null,
                span_id: null,
                trace_flags: null,
                timestamp: null,
                observed_timestamp: null,
                body: null,
                severity_text: null,
                severity_number: null,
                service_name: null,
                resource_attributes: null,
                instrumentation_scope: null,
                event_name: null,
                attributes: { existing: '\"attribute\"' },
            }

            enrichLogRecordWithJsonAttributes(record)

            expect(record.attributes).toEqual({ existing: '\"attribute\"' })
        })

        it('does nothing for non-JSON body', () => {
            const record: LogRecord = {
                uuid: 'test-uuid',
                trace_id: null,
                span_id: null,
                trace_flags: null,
                timestamp: null,
                observed_timestamp: null,
                body: 'plain text log message',
                severity_text: null,
                severity_number: null,
                service_name: null,
                resource_attributes: null,
                instrumentation_scope: null,
                event_name: null,
                attributes: null,
            }

            enrichLogRecordWithJsonAttributes(record)

            expect(record.attributes).toBeNull()
        })
    })

    describe('selected JSON attribute extraction', () => {
        it.each([false, true])('extracts objects with string wrapping=%s and a literal dotted key', (wrapped) => {
            const json = JSON.stringify({ user: { id: 'synthetic-user' }, count: 3, enabled: true })
            const source = wrapped ? JSON.stringify(json) : json
            const record = createRecord({ attributes: { 'payload.json': source, 'payload.json.count': '9' } })

            enrichLogRecordFromJsonAttribute(record, 'payload.json')

            expect(record.attributes).toEqual({
                'payload.json': source,
                'payload.json.user.id': JSON.stringify('synthetic-user'),
                'payload.json.count': '9',
                'payload.json.enabled': 'true',
            })
        })

        it.each(
            [[], ['alpha', 'beta'], ['beta', 'alpha'], [{ id: 1 }], [null, 3, true, ['nested'], { id: 2 }]].map(
                (items) => [items]
            )
        )('retains nested array %j as a single JSON-string attribute', (items) => {
            const source = JSON.stringify({ values: items })
            const record = createRecord({ attributes: { payload: source } })

            enrichLogRecordFromJsonAttribute(record, 'payload')

            expect(record.attributes).toEqual({
                payload: source,
                'payload.values': JSON.stringify(JSON.stringify(items)),
            })
        })

        it.each(['[]', '[1,2]', JSON.stringify('[1,2]'), 'null', 'true', '4', '"text"', '{broken', ''])(
            'preserves non-object input %s without extracting fields',
            (source) => {
                const record = createRecord({ attributes: { payload: source } })
                const original = structuredClone(record)
                enrichLogRecordFromJsonAttribute(record, 'payload')
                expect(record).toEqual(original)
            }
        )

        it('counts each array as one retained field', () => {
            const source = JSON.stringify(
                Object.fromEntries(Array.from({ length: 60 }, (_, index) => [`key${index}`, []]))
            )
            const record = createRecord({ attributes: { payload: source } })
            enrichLogRecordFromJsonAttribute(record, 'payload')
            expect(Object.keys(record.attributes!)).toHaveLength(51)
            expect(record.attributes!['payload.key49']).toBe(JSON.stringify('[]'))
            expect(record.attributes!['payload.key50']).toBeUndefined()
        })

        it.each([
            ['input_size', JSON.stringify({ value: 'x'.repeat(MAX_LOG_RECORD_BYTES) })],
            ['output_size', JSON.stringify({ value: '😀'.repeat(150_000) })],
            ['flatten_budget', '{"child":'.repeat(130) + '1' + '}'.repeat(130)],
            ['flatten_budget', '{"values":' + '['.repeat(130) + '1' + ']'.repeat(130) + '}'],
            ['flatten_budget', JSON.stringify({ first: Array(6000).fill(0), second: Array(6000).fill(0) })],
            [
                'flatten_budget',
                JSON.stringify(Object.fromEntries(Array.from({ length: 10_000 }, (_, index) => [index, 0]))),
            ],
        ])('skips %s atomically for oversized or complex input', async (reason, source) => {
            const record = createRecord({ attributes: { payload: source, original: 'true' } })
            const original = structuredClone(record)
            logsJsonEnrichmentSkippedCounter.reset()
            enrichLogRecordFromJsonAttribute(record, 'payload')
            expect(record).toEqual(original)
            expect((await logsJsonEnrichmentSkippedCounter.get()).values).toEqual([
                expect.objectContaining({ labels: { reason, source: 'selected_attribute' }, value: 1 }),
            ])
        })

        it('re-encodes attribute-only enrichment before decoded-record visitors', async () => {
            const record = createRecord({ attributes: { payload: JSON.stringify({ count: 7 }) } })
            const buffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', [record])
            const visitor = jest.fn()
            logProcessingDurationHistogram.reset()
            const result = await processLogMessageBuffer(
                buffer,
                { json_parse_logs_attribute_key: 'payload' },
                { onRecordsDecoded: visitor }
            )
            const [, , records] = await decodeLogRecords(result.value!)
            expect(records[0].attributes).toEqual({ ...record.attributes, 'payload.count': '7' })
            expect(visitor.mock.calls[0][0][0].attributes).toEqual(records[0].attributes)
            expect(result.pii).toEqual({ piiReplacements: 0 })
            // Extraction-only traffic needs its own duration series. Without the label, its cost
            // merges into the bucket that body parsing, scrubbing and untransformed traffic share.
            expect((await logProcessingDurationHistogram.get()).values).toContainEqual(
                expect.objectContaining({
                    metricName: 'logs_ingestion_processing_duration_seconds_count',
                    labels: expect.objectContaining({
                        json_parse_enabled: 'false',
                        pii_scrub_enabled: 'false',
                        attribute_extraction_enabled: 'true',
                    }),
                    value: 1,
                })
            )
        })

        it('gives sender attributes priority over selected JSON, then body JSON', async () => {
            const source = JSON.stringify({ sender: 'selected', selected: 'selected' })
            const record = createRecord({
                attributes: { payload: source, 'payload.sender': JSON.stringify('sender') },
                body: JSON.stringify({ payload: { sender: 'body', selected: 'body', body: 'body', items: [1] } }),
            })
            await transformDecodedLogRecordsInPlace([record], {
                json_parse_logs: true,
                json_parse_logs_attribute_key: 'payload',
            })
            expect(record.attributes).toEqual({
                payload: source,
                'payload.sender': JSON.stringify('sender'),
                'payload.selected': JSON.stringify('selected'),
                'payload.body': JSON.stringify('body'),
                'payload.items.0': '1',
            })
        })

        it('does not extract from a selected key introduced by body parsing', async () => {
            const record = createRecord({ attributes: null, body: JSON.stringify({ payload: '{"nested":true}' }) })
            await transformDecodedLogRecordsInPlace([record], {
                json_parse_logs: true,
                json_parse_logs_attribute_key: 'payload',
            })
            expect(record.attributes).toEqual({ payload: JSON.stringify('{"nested":true}') })
        })

        it('extracts from the scrubbed source rather than copying sensitive values', async () => {
            const record = createRecord({
                attributes: { payload: JSON.stringify({ authorization: 'Bearer synthetic_test_credential' }) },
            })
            const pii = await transformDecodedLogRecordsInPlace([record], {
                pii_scrub_logs: true,
                json_parse_logs_attribute_key: 'payload',
            })
            expect(pii.piiReplacements).toBeGreaterThan(0)
            expect(record.attributes).toEqual({
                payload: JSON.stringify({ authorization: `Bearer ${PII_REDACTED}` }),
                'payload.authorization': JSON.stringify(`Bearer ${PII_REDACTED}`),
            })
        })
    })

    describe('processLogMessageBuffer', () => {
        it('processes buffer with JSON parsing enabled', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ level: 'info', message: 'test' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const { value: outputBuffer, pii } = await processLogMessageBuffer(inputBuffer, { json_parse_logs: true })
            expect(pii).toEqual({ piiReplacements: 0 })
            const [_, __, decoded] = await decodeLogRecords(outputBuffer!)

            expect(decoded[0]?.attributes).toEqual({
                level: '\"info\"',
                message: '\"test\"',
            })
        })

        it('processes multiple records in buffer', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid-1',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ level: 'info', message: 'test1' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
                {
                    uuid: 'test-uuid-2',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ level: 'error', message: 'test2' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const { value: outputBuffer, pii } = await processLogMessageBuffer(inputBuffer, { json_parse_logs: true })
            expect(pii).toEqual({ piiReplacements: 0 })
            const [_, __, decoded] = await decodeLogRecords(outputBuffer!)

            expect(decoded).toHaveLength(2)
            expect(decoded[0]?.attributes).toEqual({
                level: '\"info\"',
                message: '\"test1\"',
            })
            expect(decoded[1]?.attributes).toEqual({
                level: '\"error\"',
                message: '\"test2\"',
            })
        })

        it('returns original buffer when JSON parse and PII scrub are disabled', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ level: 'info', message: 'test' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const { value: out, pii } = await processLogMessageBuffer(inputBuffer, {
                json_parse_logs: false,
                pii_scrub_logs: false,
            })

            expect(out).toBe(inputBuffer)
            expect(pii).toEqual({ piiReplacements: 0 })
        })

        it('forwards the original buffer when only a visitor ran', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ level: 'info', message: 'test' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const onRecordsDecoded = jest.fn()
            const { value: out } = await processLogMessageBuffer(
                inputBuffer,
                { json_parse_logs: false, pii_scrub_logs: false },
                { onRecordsDecoded }
            )

            // The visitor forces a decode, but nothing mutated the records, so the buffer is returned by
            // identity rather than re-encoded.
            expect(onRecordsDecoded).toHaveBeenCalledTimes(1)
            expect(onRecordsDecoded.mock.calls[0][0]).toHaveLength(1)
            expect(out).toBe(inputBuffer)
        })

        it.each([
            ['everything off', {}, 0, false, 'passthrough'],
            ['json parse on', { json_parse_logs: true }, 0, false, 'decode_and_reencode'],
            ['pii scrub on', { pii_scrub_logs: true }, 0, false, 'decode_and_reencode'],
            ['attribute extraction on', { json_parse_logs_attribute_key: 'payload' }, 0, false, 'decode_and_reencode'],
            ['empty attribute key', { json_parse_logs_attribute_key: '' }, 0, false, 'passthrough'],
            ['a stage present', {}, 1, false, 'decode_and_reencode'],
            ['a decoded-records visitor present', {}, 0, true, 'decode_only'],
            ['a visitor and a stage', {}, 1, true, 'decode_and_reencode'],
        ])('bufferProcessingMode: %s', (_name, settings, stageCount, hasVisitor, expected) => {
            expect(bufferProcessingMode(settings, stageCount, hasVisitor)).toEqual(expected)
        })

        it('decodes and scrubs only when PII scrub is on without JSON parse', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ level: 'info', message: 'user@example.com' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const { value: outputBuffer, pii } = await processLogMessageBuffer(inputBuffer, {
                json_parse_logs: false,
                pii_scrub_logs: true,
            })
            expect(outputBuffer).not.toBe(inputBuffer)
            expect(pii.piiReplacements).toBeGreaterThanOrEqual(1)

            const [_, __, decoded] = await decodeLogRecords(outputBuffer!)
            expect(decoded[0]?.attributes).toBeNull()
            const body = parseJSON(decoded[0]?.body || '{}') as { message?: string }
            expect(body.message).not.toContain('example.com')
            expect(body.message).toContain('{{REDACTED}}')
        })

        it('scrubs log attributes when json parse is off and pii scrub is on', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: 'plain',
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: { note: 'only-attr@example.com' },
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const { value: outputBuffer, pii } = await processLogMessageBuffer(inputBuffer, {
                json_parse_logs: false,
                pii_scrub_logs: true,
            })
            expect(pii.piiReplacements).toBe(1)
            const [_, __, decoded] = await decodeLogRecords(outputBuffer!)
            expect(decoded[0]?.body).toBe('plain')
            expect(decoded[0]?.attributes).toEqual({ note: PII_REDACTED })
        })

        it('scrubs body then enriches when both JSON parse and PII scrub are on', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ level: 'info', message: 'a@b.co' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: { note: 'c@d.co' },
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const { value: outputBuffer, pii } = await processLogMessageBuffer(inputBuffer, {
                json_parse_logs: true,
                pii_scrub_logs: true,
            })
            expect(pii.piiReplacements).toBe(2)
            const [_, __, decoded] = await decodeLogRecords(outputBuffer!)
            expect(decoded[0]?.attributes).toEqual({
                level: encodeAttributeCell('info'),
                message: encodeAttributeCell(PII_REDACTED),
                note: PII_REDACTED,
            })
        })

        it('does not call parseLogBodyForIngestion when only PII scrub is on', async () => {
            const spy = jest.spyOn(logBodyParse, 'parseLogBodyForIngestion')
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ level: 'info', message: 'only@pii.test' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            await processLogMessageBuffer(inputBuffer, {
                json_parse_logs: false,
                pii_scrub_logs: true,
            })

            expect(spy).not.toHaveBeenCalled()
            spy.mockRestore()
        })

        it('calls parseLogBodyForIngestion once per record when both JSON parse and PII scrub are on', async () => {
            const spy = jest.spyOn(logBodyParse, 'parseLogBodyForIngestion')
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ level: 'info', message: 'once@parse.test' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
                {
                    uuid: 'test-uuid-2',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ level: 'warn', message: 'two@parse.test' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            await processLogMessageBuffer(inputBuffer, {
                json_parse_logs: true,
                pii_scrub_logs: true,
            })

            expect(spy).toHaveBeenCalledTimes(2)
            spy.mockRestore()
        })

        it('flattens nested JSON keys when both flags are on; body is pattern-scrubbed only', async () => {
            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify({ meta: { api_key: 'leak-value' }, ok: 'keep' }),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const { value: outputBuffer, pii } = await processLogMessageBuffer(inputBuffer, {
                json_parse_logs: true,
                pii_scrub_logs: true,
            })
            expect(pii).toEqual({ piiReplacements: 0 })
            const [_, __, decoded] = await decodeLogRecords(outputBuffer!)
            const body = parseJSON(decoded[0]?.body || '{}') as { meta: { api_key: string }; ok: string }
            // Body is pattern-scrubbed only; nested JSON keys are not redacted by key name.
            expect(body.meta.api_key).toBe('leak-value')
            expect(body.ok).toBe('keep')
            expect(decoded[0]?.attributes).toEqual({
                'meta.api_key': encodeAttributeCell('leak-value'),
                ok: encodeAttributeCell('keep'),
            })
        })

        it('rejects promise for invalid AVRO data', async () => {
            const invalidBuffer = Buffer.from('not avro data')

            await expect(processLogMessageBuffer(invalidBuffer, { json_parse_logs: true })).rejects.toThrow()
            await expect(
                processLogMessageBuffer(invalidBuffer, { json_parse_logs: false, pii_scrub_logs: true })
            ).rejects.toThrow()
        })

        it('limits attributes to 50 when parsing JSON body', async () => {
            const largeObject: Record<string, string> = {}
            for (let i = 0; i < 100; i++) {
                largeObject[`key${i}`] = `value${i}`
            }

            const records: LogRecord[] = [
                {
                    uuid: 'test-uuid',
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: null,
                    observed_timestamp: null,
                    body: JSON.stringify(largeObject),
                    severity_text: null,
                    severity_number: null,
                    service_name: null,
                    resource_attributes: null,
                    instrumentation_scope: null,
                    event_name: null,
                    attributes: null,
                    bytes_uncompressed: null,
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const { value: outputBuffer, pii } = await processLogMessageBuffer(inputBuffer, { json_parse_logs: true })
            expect(pii).toEqual({ piiReplacements: 0 })
            const [_, __, decoded] = await decodeLogRecords(outputBuffer!)

            expect(Object.keys(decoded[0]?.attributes || {}).length).toBe(50)
        })
    })
})

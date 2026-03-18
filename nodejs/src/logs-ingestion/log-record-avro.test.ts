import avro from 'avsc'

import {
    LogRecord,
    decodeLogRecords,
    encodeLogRecords,
    enrichLogRecordWithJsonAttributes,
    extractJsonAttributesFromBody,
    flattenJson,
    processLogMessageBuffer,
} from './log-record-avro'

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
    }
]
}`)

describe('log-record-avro', () => {
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
        ])('%s', (_, input, expected) => {
            expect(flattenJson(input)).toEqual(expected)
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

            expect(Object.keys(result).length).toBe(50)
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
                },
            ]

            const encoded = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const [_, __, decoded] = await decodeLogRecords(encoded)

            expect(decoded).toEqual(records)
        })

        it('rejects promise for invalid buffer', async () => {
            const invalidBuffer = Buffer.from('not avro data')

            await expect(decodeLogRecords(invalidBuffer)).rejects.toThrow()
        })
    })

    describe('enrichLogRecordWithJsonAttributes', () => {
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
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const outputBuffer = await processLogMessageBuffer(inputBuffer, { json_parse_logs: true })
            const [_, __, decoded] = await decodeLogRecords(outputBuffer)

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
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const outputBuffer = await processLogMessageBuffer(inputBuffer, { json_parse_logs: true })
            const [_, __, decoded] = await decodeLogRecords(outputBuffer)

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

        it('returns original buffer when JSON parsing disabled', async () => {
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
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const outputBuffer = await processLogMessageBuffer(inputBuffer, { json_parse_logs: false })

            expect(outputBuffer).toBe(inputBuffer)
        })

        it('rejects promise for invalid AVRO data', async () => {
            const invalidBuffer = Buffer.from('not avro data')

            await expect(processLogMessageBuffer(invalidBuffer, { json_parse_logs: true })).rejects.toThrow()
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
                },
            ]

            const inputBuffer = await encodeLogRecords(LOG_RECORD_SCHEMA, 'zstandard', records)
            const outputBuffer = await processLogMessageBuffer(inputBuffer, { json_parse_logs: true })
            const [_, __, decoded] = await decodeLogRecords(outputBuffer)

            expect(Object.keys(decoded[0]?.attributes || {}).length).toBe(50)
        })
    })
})

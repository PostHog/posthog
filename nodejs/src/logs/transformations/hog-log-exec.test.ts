import { compileHog } from '~/cdp/templates/compiler'
import { parseJSON } from '~/common/utils/json-parse'

import type { LogRecord } from '../log-record-avro'
import {
    MAX_LOG_TRANSFORMATION_PRINT_LOGS,
    applyTransformResult,
    buildLogRecordGlobals,
    executeLogTransformation,
    resolveLogTransformationInputs,
} from './hog-log-exec'

jest.setTimeout(30_000)

const PROJECT = { id: 1, name: 'test', url: 'http://localhost:8010/project/1' }

const createRecord = (overrides: Partial<LogRecord> = {}): LogRecord => ({
    uuid: '0197a3f2-1111-7000-8000-000000000001',
    trace_id: Buffer.from('0123456789abcdef0123456789abcdef', 'hex'),
    span_id: Buffer.from('0123456789abcdef', 'hex'),
    trace_flags: 0,
    timestamp: 1_780_000_000_000_000_000,
    observed_timestamp: 1_780_000_000_000_000_000,
    body: 'user jane@example.com logged in',
    severity_text: 'info',
    severity_number: 9,
    service_name: 'auth-api',
    // Attribute values are JSON-encoded on the wire, like capture produces them
    resource_attributes: { 'k8s.namespace.name': '"auth"' },
    instrumentation_scope: 'auth.sessions',
    event_name: null,
    attributes: { 'http.method': '"POST"', user_email: '"jane@example.com"' },
    bytes_uncompressed: 120,
    ...overrides,
})

const run = async (hog: string, record: LogRecord, inputs: Record<string, unknown> = {}, options = {}) => {
    const bytecode = await compileHog(hog)
    const globals = buildLogRecordGlobals(record, PROJECT, inputs)
    return executeLogTransformation(bytecode, record, globals, options)
}

describe('hog-log-exec', () => {
    describe('buildLogRecordGlobals', () => {
        it('exposes record fields with buffers hex-encoded and nulls normalized', () => {
            const globals = buildLogRecordGlobals(createRecord({ attributes: null }), PROJECT, { foo: 'bar' })

            expect(globals.record.trace_id).toBe('0123456789abcdef0123456789abcdef')
            expect(globals.record.span_id).toBe('0123456789abcdef')
            expect(globals.record.attributes).toEqual({})
            expect(globals.record.body).toBe('user jane@example.com logged in')
            expect(globals.inputs).toEqual({ foo: 'bar' })
            expect(globals.project).toBe(PROJECT)
        })
    })

    describe('resolveLogTransformationInputs', () => {
        it('reports the VM time spent on hog-templated inputs so callers can charge budgets', async () => {
            const record = createRecord()
            const { inputs, durationMs } = resolveLogTransformationInputs(
                {
                    inputs: {
                        svc: {
                            value: 'service = {record.service_name}',
                            bytecode: await compileHog(`return f'service = {record.service_name}'`),
                            order: 0,
                        },
                    },
                    encrypted_inputs: null,
                } as any,
                buildLogRecordGlobals(record, PROJECT, {}),
                10
            )
            expect(inputs.svc).toBe('service = auth-api')
            expect(durationMs).toBeGreaterThan(0)
        })
    })

    describe('executeLogTransformation', () => {
        it('mutates body and attributes in place', async () => {
            const record = createRecord()
            const outcome = await run(
                `
                let rec := record
                rec.body := replaceAll(rec.body, 'jane@example.com', '[REDACTED]')
                rec.attributes.user_email := sha256Hex(rec.attributes.user_email)
                return rec
                `,
                record
            )

            expect(outcome.status).toBe('mutated')
            expect(record.body).toBe('user [REDACTED] logged in')
            expect(parseJSON(record.attributes!.user_email)).toMatch(/^[a-f0-9]{64}$/)
            expect(record.attributes!['http.method']).toBe('"POST"')
        })

        it('passes resolved inputs through globals', async () => {
            const record = createRecord()
            const outcome = await run(
                `
                let rec := record
                rec.attributes.tagged := inputs.tag
                return rec
                `,
                record,
                { tag: 'from-input' }
            )

            expect(outcome.status).toBe('mutated')
            expect(record.attributes!.tagged).toBe('"from-input"')
        })

        it('matches conditions against decoded attribute values, as shown in the UI', async () => {
            // Wire values are JSON-encoded ('"POST"'); customer code must be able to
            // compare against the plain value the Logs UI displays.
            const record = createRecord()
            const outcome = await run(
                `
                if (record.attributes['http.method'] == 'POST') {
                    return null
                }
                return record
                `,
                record
            )
            expect(outcome.status).toBe('dropped')
        })

        it('drops the record when the transformation returns null', async () => {
            const outcome = await run(`return null`, createRecord())
            expect(outcome.status).toBe('dropped')
        })

        it('ignores read-only fields in the returned record', async () => {
            const record = createRecord()
            const outcome = await run(
                `
                let rec := record
                rec.service_name := 'spoofed-service'
                rec.timestamp := 1
                rec.body := 'changed'
                return rec
                `,
                record
            )

            expect(outcome.status).toBe('mutated')
            expect(record.body).toBe('changed')
            expect(record.service_name).toBe('auth-api')
            expect(record.timestamp).toBe(1_780_000_000_000_000_000)
            expect(record.bytes_uncompressed).toBe(120)
        })

        it.each([
            ['a string', `return 'nope'`],
            ['a number', `return 42`],
            ['a list', `return [1, 2]`],
            ['a non-string body', `let rec := record\nrec.body := 42\nreturn rec`],
        ])('fails open without mutating when the result is %s', async (_desc, hog) => {
            const record = createRecord()
            const originalBody = record.body
            const outcome = await run(hog, record)

            expect(outcome.status).toBe('failed')
            expect(record.body).toBe(originalBody)
            expect(record.attributes).toEqual(createRecord().attributes)
        })

        it('stringifies non-string attribute values', async () => {
            const record = createRecord()
            const outcome = await run(
                `
                let rec := record
                rec.attributes.retry_count := 3
                return rec
                `,
                record
            )

            expect(outcome.status).toBe('mutated')
            expect(record.attributes!.retry_count).toBe('3')
        })

        it('kills runaway programs via the timeout', async () => {
            const record = createRecord()
            const outcome = await run(
                `
                let i := 0
                while (true) {
                    i := i + 1
                }
                return record
                `,
                record,
                {},
                { timeoutMs: 5 }
            )

            expect(outcome.status).toBe('failed')
            if (outcome.status === 'failed') {
                expect(outcome.error).toContain('timed out')
            }
            expect(outcome.durationMs).toBeGreaterThanOrEqual(4)
        })

        it('kills memory-hungry programs via the memory limit', async () => {
            const record = createRecord()
            const outcome = await run(
                `
                let s := 'xxxxxxxxxxxxxxxx'
                for (let i := 0; i < 30; i := i + 1) {
                    s := concat(s, s)
                }
                return record
                `,
                record,
                {},
                { timeoutMs: 1000 }
            )

            expect(outcome.status).toBe('failed')
            if (outcome.status === 'failed') {
                expect(outcome.error.toLowerCase()).toContain('memory')
            }
        })

        it('captures print output up to the cap and redacts sensitive values', async () => {
            const record = createRecord()
            const outcome = await run(
                `
                for (let i := 0; i < 10; i := i + 1) {
                    print('iteration', i, 'secret-value')
                }
                return record
                `,
                record,
                {},
                { sensitiveValues: ['secret-value'] }
            )

            expect(outcome.status).toBe('mutated')
            expect(outcome.logs).toHaveLength(MAX_LOG_TRANSFORMATION_PRINT_LOGS)
            expect(outcome.logs[0]).toBe('iteration, 0, ***REDACTED***')
        })
    })

    describe('applyTransformResult', () => {
        it('treats undefined and false like null (drop)', () => {
            const record = createRecord()
            expect(applyTransformResult(record, undefined)).toBe('dropped')
            expect(applyTransformResult(record, false)).toBe('dropped')
            expect(applyTransformResult(record, null)).toBe('dropped')
        })

        it('rejects invalid severity_text without mutating', () => {
            const record = createRecord()
            expect(applyTransformResult(record, { body: 'new', severity_text: 7 })).toBe('invalid')
            expect(record.body).toBe('user jane@example.com logged in')
            expect(record.severity_text).toBe('info')
        })

        it('allows clearing body to null', () => {
            const record = createRecord()
            expect(applyTransformResult(record, { body: null })).toBe('mutated')
            expect(record.body).toBeNull()
        })

        it('allows clearing attribute maps to null, like body', () => {
            const record = createRecord()
            expect(applyTransformResult(record, { attributes: null, resource_attributes: null })).toBe('mutated')
            expect(record.attributes).toBeNull()
            expect(record.resource_attributes).toBeNull()
        })

        it('preserves the exact wire encoding of attribute values the transformation left untouched', async () => {
            // '"3"' (string) and '3' (number) both decode to '3'; only the original wire
            // form can restore the type, so untouched values must round-trip byte-identically.
            const record = createRecord({
                attributes: { str_num: '"3"', real_num: '3', flag: 'true', keep: '"plain"' },
            })
            const outcome = await run(`return record`, record)
            expect(outcome.status).toBe('mutated')
            expect(record.attributes).toEqual({ str_num: '"3"', real_num: '3', flag: 'true', keep: '"plain"' })
        })
    })
})

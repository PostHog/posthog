import { parseJSON } from '~/common/utils/json-parse'
import type { LogRecord } from '~/logs/log-record-avro'
import {
    LogTransformationOutcome,
    buildLogRecordGlobals,
    executeLogTransformation,
} from '~/logs/transformations/hog-log-exec'

import { compileHog } from '../compiler'
import { template as logDefaultTemplate } from './default/default.template'
import { template as logDropBySeverityTemplate } from './drop-by-severity/drop-by-severity.template'
import { template as logPiiScrubTemplate } from './pii-scrub/pii-scrub.template'
import { template as logRedactAttributesTemplate } from './redact-attributes/redact-attributes.template'

jest.setTimeout(30_000)

const PROJECT = { id: 1, name: 'test', url: 'http://localhost:8010/project/1' }

const createRecord = (overrides: Partial<LogRecord> = {}): LogRecord => ({
    uuid: '0197a3f2-1111-7000-8000-000000000001',
    trace_id: null,
    span_id: null,
    trace_flags: 0,
    timestamp: 1_780_000_000_000_000_000,
    observed_timestamp: 1_780_000_000_000_000_000,
    body: 'user jane@example.com logged in',
    severity_text: 'info',
    severity_number: 9,
    service_name: 'auth-api',
    resource_attributes: { 'k8s.namespace.name': 'auth' },
    instrumentation_scope: 'auth.sessions',
    event_name: null,
    attributes: { 'http.method': 'POST' },
    bytes_uncompressed: 120,
    ...overrides,
})

const run = async (
    code: string,
    record: LogRecord,
    inputs: Record<string, unknown> = {}
): Promise<{ outcome: LogTransformationOutcome; record: LogRecord }> => {
    const bytecode = await compileHog(code)
    const globals = buildLogRecordGlobals(record, PROJECT, inputs)
    const outcome = executeLogTransformation(bytecode, record, globals, {})
    return { outcome, record }
}

describe('transformation_log templates', () => {
    describe('default', () => {
        it('returns the record unchanged', async () => {
            const { outcome, record } = await run(logDefaultTemplate.code, createRecord())
            expect(outcome.status).toEqual('mutated')
            expect(record.body).toEqual('user jane@example.com logged in')
        })
    })

    describe('pii-scrub', () => {
        it('redacts emails, API keys, and bearer tokens from the body', async () => {
            const body = 'login jane@example.com key sk_live_abcdef123456 auth Bearer abcdef012345 done'
            const { outcome, record } = await run(logPiiScrubTemplate.code, createRecord({ body }), {
                replacement: '[REDACTED]',
            })
            expect(outcome.status).toEqual('mutated')
            expect(record.body).toEqual('login [REDACTED] key [REDACTED] auth [REDACTED] done')
        })

        it('honors a custom replacement value', async () => {
            const { record } = await run(logPiiScrubTemplate.code, createRecord({ body: 'x jane@example.com y' }), {
                replacement: '***',
            })
            expect(record.body).toEqual('x *** y')
        })

        it('leaves a null body untouched', async () => {
            const { outcome, record } = await run(logPiiScrubTemplate.code, createRecord({ body: null }), {
                replacement: '[REDACTED]',
            })
            expect(outcome.status).toEqual('mutated')
            expect(record.body).toBeNull()
        })
    })

    describe('drop-by-severity', () => {
        it('drops a configured severity', async () => {
            const { outcome } = await run(logDropBySeverityTemplate.code, createRecord({ severity_text: 'debug' }), {
                severitiesToDrop: 'debug,trace',
            })
            expect(outcome.status).toEqual('dropped')
        })

        it('keeps severities not in the list', async () => {
            const { outcome } = await run(logDropBySeverityTemplate.code, createRecord({ severity_text: 'error' }), {
                severitiesToDrop: 'debug,trace',
            })
            expect(outcome.status).toEqual('mutated')
        })

        it('matches case-insensitively against the lowercased severity', async () => {
            const { outcome } = await run(logDropBySeverityTemplate.code, createRecord({ severity_text: 'debug' }), {
                severitiesToDrop: 'DEBUG',
            })
            expect(outcome.status).toEqual('dropped')
        })
    })

    describe('redact-attributes', () => {
        it('replaces configured attribute values with a sha256 hash', async () => {
            const { outcome, record } = await run(
                logRedactAttributesTemplate.code,
                createRecord({ attributes: { user_email: '"jane@example.com"', keep: '"me"' } }),
                { attributeKeys: 'user_email' }
            )
            expect(outcome.status).toEqual('mutated')
            const attributes = record.attributes ?? {}
            expect(parseJSON(attributes.user_email)).toMatch(/^[a-f0-9]{64}$/)
            expect(attributes.keep).toEqual('"me"')
        })

        it('ignores attribute keys that are not present', async () => {
            const { outcome, record } = await run(
                logRedactAttributesTemplate.code,
                createRecord({ attributes: { keep: '"me"' } }),
                { attributeKeys: 'user_email,user.id' }
            )
            expect(outcome.status).toEqual('mutated')
            expect(record.attributes).toEqual({ keep: '"me"' })
        })
    })
})

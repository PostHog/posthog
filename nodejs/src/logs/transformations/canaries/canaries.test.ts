import { compileHog } from '~/cdp/templates/compiler'

import type { LogRecord } from '../../log-record-avro'
import { buildLogRecordGlobals, executeLogTransformation } from '../hog-log-exec'
import type { LogTransformationOutcome } from '../hog-log-exec'
import { CANARIES, CANARY_FAKE_SECRET, CANARY_SERVICE, type CanaryDefinition } from './canaries'

jest.setTimeout(30_000)

const PROJECT = { id: 2, name: 'test', url: 'http://localhost:8010/project/2' }

const byName = (name: string): CanaryDefinition => {
    const found = CANARIES.find((c) => c.name === name)
    if (!found) {
        throw new Error(`no canary named ${name}`)
    }
    return found
}

/** Attribute maps on a LogRecord are JSON-encoded on the wire; string values carry quotes. */
const enc = (attrs: Record<string, string>): Record<string, string> =>
    Object.fromEntries(Object.entries(attrs).map(([k, v]) => [k, JSON.stringify(v)]))

const createRecord = (overrides: Partial<LogRecord> = {}): LogRecord => ({
    uuid: '0197a3f2-1111-7000-8000-000000000001',
    trace_id: null,
    span_id: null,
    trace_flags: 0,
    timestamp: 1_780_000_000_000_000_000,
    observed_timestamp: 1_780_000_000_000_000_000,
    body: 'request completed',
    severity_text: 'info',
    severity_number: 9,
    service_name: 'posthog-web-django-granian',
    resource_attributes: enc({ 'k8s.namespace.name': 'posthog' }),
    instrumentation_scope: 'django.request',
    event_name: null,
    attributes: enc({ 'http.method': 'POST' }),
    bytes_uncompressed: 120,
    ...overrides,
})

/** A canary record in a given test case. */
const canaryRecord = (testCase: string | null, overrides: Partial<LogRecord> = {}): LogRecord =>
    createRecord({
        service_name: CANARY_SERVICE,
        attributes: enc(testCase ? { 'canary.case': testCase } : {}),
        ...overrides,
    })

const run = async (
    canary: CanaryDefinition,
    record: LogRecord
): Promise<{ outcome: LogTransformationOutcome; record: LogRecord }> => {
    const bytecode = await compileHog(canary.hog)
    const globals = buildLogRecordGlobals(record, PROJECT, {})
    // Resolve declared inputs the same way the transformer service does.
    const inputs = Object.fromEntries(Object.entries(canary.inputs).map(([k, v]) => [k, v.value]))
    globals.inputs = inputs
    const sensitiveValues = canary.inputs_schema
        .filter((s) => s.secret)
        .map((s) => String(canary.inputs[String(s.key)]?.value ?? ''))
        .filter(Boolean)
    const outcome = executeLogTransformation(bytecode, record, globals, { sensitiveValues })
    return { outcome, record }
}

describe('log transformation production canaries', () => {
    /**
     * The whole safety argument rests on this. A log transformation has no filters, so once
     * enabled it runs against every record for the team — if the guard leaks, these canaries
     * are loose on billions of real production log records.
     */
    describe('blast radius', () => {
        it.each(CANARIES.map((c) => [c.name, c] as const))(
            '%s leaves a real production record completely untouched',
            async (_name, canary) => {
                const record = createRecord()
                const before = structuredClone(record)

                const { outcome } = await run(canary, record)

                expect(outcome.status).toEqual('mutated')
                expect(record).toEqual(before)
            }
        )

        /**
         * Pins a platform behaviour the canaries inherit rather than cause: buildLogRecordGlobals
         * runs null attribute maps through decodeAttributeMap, which returns {} for null. A
         * passthrough `return record` therefore hands back a record whose attributes key is
         * present and empty, and applyTransformResult writes it. So enabling ANY log
         * transformation — including the shipped default template — rewrites null attribute maps
         * to empty maps on every record that has none. Everything else still round-trips exactly.
         */
        it.each(CANARIES.map((c) => [c.name, c] as const))(
            '%s leaves a null-attribute record untouched except for null-to-empty-map normalisation',
            async (_name, canary) => {
                const record = createRecord({ body: null, attributes: null, resource_attributes: null })
                const before = structuredClone(record)

                const { outcome } = await run(canary, record)

                expect(outcome.status).toEqual('mutated')
                expect(record.attributes).toEqual({})
                expect(record.resource_attributes).toEqual({})
                expect({ ...record, attributes: null, resource_attributes: null }).toEqual(before)
            }
        )

        it('guards on the configured service name, not a hardcoded one', async () => {
            const canary = byName('canary-1-mutate-and-readonly')
            // A record using the canary service name is only in scope because the input says so.
            const record = createRecord({ service_name: 'some-other-canary' })
            const before = structuredClone(record)

            await run(canary, record)

            expect(record).toEqual(before)
        })
    })

    describe('canary-1-mutate-and-readonly', () => {
        it('writes body, severity_text, attributes and resource_attributes', async () => {
            const record = canaryRecord('mutate', { body: 'token CANARY_REDACT_ME here' })

            const { outcome } = await run(byName('canary-1-mutate-and-readonly'), record)

            expect(outcome.status).toEqual('mutated')
            expect(record.body).toEqual('token [REDACTED] here')
            expect(record.severity_text).toEqual('warn')
            expect(record.attributes?.['canary.t1']).toEqual('"applied"')
            expect(record.resource_attributes?.['canary.t1.resource']).toEqual('"applied"')
        })

        it('cannot write the read-only fields', async () => {
            const traceId = Buffer.from('aabbccddeeff00112233445566778899', 'hex')
            const record = canaryRecord('mutate', { trace_id: traceId })

            await run(byName('canary-1-mutate-and-readonly'), record)

            expect(record.service_name).toEqual(CANARY_SERVICE)
            expect(record.severity_number).toEqual(9)
            expect(record.timestamp).toEqual(1_780_000_000_000_000_000)
            expect(record.trace_id).toEqual(traceId)
            expect(record.event_name).toBeNull()
        })

        it('leaves body and severity alone outside the mutate case', async () => {
            const record = canaryRecord(null, { body: 'token CANARY_REDACT_ME here' })

            await run(byName('canary-1-mutate-and-readonly'), record)

            expect(record.body).toEqual('token CANARY_REDACT_ME here')
            expect(record.severity_text).toEqual('info')
            expect(record.attributes?.['canary.chain']).toEqual('"a"')
        })

        /**
         * Pins the attribute wire-encoding edge case the canary probes in production.
         * encodeLogAttributeValue passes already-valid JSON straight through, so the string
         * '1' is stored bare rather than quoted — unlike every other string value written
         * here. The sink reads string attributes with JSONExtractString, so a bare 1 is not
         * expected to survive as "1" in the UI.
         */
        it('stores a numeric-looking string attribute unquoted', async () => {
            const record = canaryRecord(null)

            await run(byName('canary-1-mutate-and-readonly'), record)

            expect(record.attributes?.['canary.numeric']).toEqual('1')
            expect(record.attributes?.['canary.numeric']).not.toEqual('"1"')
        })
    })

    describe('canary-2-drop-and-chain', () => {
        it('drops the record in the drop case', async () => {
            const record = canaryRecord('drop')

            const { outcome } = await run(byName('canary-2-drop-and-chain'), record)

            expect(outcome.status).toEqual('dropped')
        })

        it('keeps the record in every other case', async () => {
            const record = canaryRecord('mutate')

            const { outcome } = await run(byName('canary-2-drop-and-chain'), record)

            expect(outcome.status).toEqual('mutated')
        })

        it('appends to the marker canary 1 wrote, proving execution order', async () => {
            const record = canaryRecord(null)

            await run(byName('canary-1-mutate-and-readonly'), record)
            await run(byName('canary-2-drop-and-chain'), record)

            expect(record.attributes?.['canary.chain']).toEqual('"ab"')
        })
    })

    describe('canary-3-fail-open', () => {
        it.each([
            ['returns a non-record', 'fail-invalid'],
            ['never terminates', 'fail-timeout'],
        ])('fails open when the transformation %s', async (_label, testCase) => {
            const record = canaryRecord(testCase, { body: 'untouched' })
            const before = structuredClone(record)

            const { outcome } = await run(byName('canary-3-fail-open'), record)

            expect(outcome.status).toEqual('failed')
            expect(record).toEqual(before)
        })

        it('succeeds normally outside the failure cases', async () => {
            const record = canaryRecord('mutate')

            const { outcome } = await run(byName('canary-3-fail-open'), record)

            expect(outcome.status).toEqual('mutated')
            expect(record.attributes?.['canary.t3']).toEqual('"reached"')
        })
    })

    describe('canary-4-secret-redaction', () => {
        it('scrubs the encrypted input from the body, the attributes and the logs', async () => {
            const record = canaryRecord('leak')

            const { outcome } = await run(byName('canary-4-secret-redaction'), record)

            expect(outcome.status).toEqual('mutated')
            expect(record.body).not.toContain(CANARY_FAKE_SECRET)
            expect(record.attributes?.['canary.leak']).not.toContain(CANARY_FAKE_SECRET)
            expect(outcome.logs.join('\n')).not.toContain(CANARY_FAKE_SECRET)
            // The write still happened — only the secret itself is scrubbed.
            expect(record.body).toContain('leak-in-body:')
        })

        it('is a no-op outside the leak case', async () => {
            const record = canaryRecord('mutate', { body: 'untouched' })
            const before = structuredClone(record)

            await run(byName('canary-4-secret-redaction'), record)

            expect(record).toEqual(before)
        })
    })

    describe('definitions', () => {
        /**
         * Structural backstop for the blast-radius property above. The behavioural tests only
         * prove the guard holds for the record shapes they happen to use; this proves no canary
         * can ever run a statement before deciding the record is in scope.
         */
        it('guards on the service name as the first statement of every canary', () => {
            for (const canary of CANARIES) {
                const firstLine = canary.hog.trim().split('\n')[0]
                expect(firstLine).toEqual('if (record.service_name != inputs.canaryService) {')
            }
        })

        it('never carries a real credential in a secret input', () => {
            for (const canary of CANARIES) {
                const secretKeys = canary.inputs_schema.filter((s) => s.secret).map((s) => String(s.key))
                for (const key of secretKeys) {
                    expect(canary.inputs[key]?.value).toEqual(CANARY_FAKE_SECRET)
                }
            }
        })

        it('can all be enabled at once under the per-team cap', () => {
            // MAX_LOG_TRANSFORMATIONS_PER_TEAM in products/cdp/backend/api/hog_function.py
            expect(CANARIES.length).toBeLessThanOrEqual(5)
        })
    })
})

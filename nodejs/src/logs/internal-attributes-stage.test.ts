import { makeInternalAttributesStage } from './internal-attributes-stage'
import type { InternalLogs } from './internal-logs'
import type { LogRecord } from './log-record-avro'

const makeRecord = (attributes: Record<string, string> | null): LogRecord => ({
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
    attributes,
})

const hogFlow: InternalLogs = {
    source: 'hog_flow',
    billed: false,
    teamRules: false,
    serviceName: 'posthog-internal-workflows',
    attributes: ['hog_flow.id'],
}

const spoofed = {
    'posthog.internal.source': '"hog_function"',
    'posthog.internal.hog_flow.id': '"flow-1"',
    'posthog.internal.batch_export.id': '"export-1"',
    'http.method': '"GET"',
}

describe('makeInternalAttributesStage', () => {
    it.each([
        ['an unverified batch loses every internal key', undefined, spoofed, { 'http.method': '"GET"' }],
        [
            'a verified batch keeps allowed keys and gets its source from the signature',
            hogFlow,
            spoofed,
            {
                'posthog.internal.source': '"hog_flow"',
                'posthog.internal.hog_flow.id': '"flow-1"',
                'http.method': '"GET"',
            },
        ],
        [
            'a verified record without attributes still gets its source',
            hogFlow,
            null,
            { 'posthog.internal.source': '"hog_flow"' },
        ],
    ])('%s', async (_name, verified, attributes, expected) => {
        const record = makeRecord(attributes && { ...attributes })

        await makeInternalAttributesStage(verified).run([record])

        expect(record.attributes ?? {}).toEqual(expected)
    })
})

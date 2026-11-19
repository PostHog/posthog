import type { LogRecord } from '../log-record-avro'
import { type CompiledMetricRule } from './compile-metric-rules'
import { DEFAULT_METRIC_RULES, withDefaultMetricRules } from './default-metric-rules'
import { createBatchTallies, tallyRecords } from './tally'

const NOW_MS = 1_700_000_000_000

const spanRecord = (overrides: Record<string, unknown> = {}): LogRecord =>
    ({
        uuid: null,
        trace_id: null,
        span_id: null,
        trace_flags: null,
        timestamp: NOW_MS * 1000,
        end_time: NOW_MS * 1000 + 40_000, // 40ms
        observed_timestamp: null,
        body: null,
        severity_text: null,
        severity_number: null,
        service_name: 'api',
        resource_attributes: {},
        instrumentation_scope: null,
        event_name: null,
        attributes: {},
        name: 'GET /checkout',
        kind: 2, // SERVER
        status_code: 1, // OK
        status_message: null,
        ...overrides,
    }) as unknown as LogRecord

const logRecord = (overrides: Partial<LogRecord> = {}): LogRecord => ({
    uuid: null,
    trace_id: null,
    span_id: null,
    trace_flags: null,
    timestamp: NOW_MS * 1000,
    observed_timestamp: null,
    body: 'hello',
    severity_text: 'ERROR',
    severity_number: 17,
    service_name: 'api',
    resource_attributes: {},
    instrumentation_scope: null,
    event_name: null,
    attributes: {},
    ...overrides,
})

function tallyDefaults(source: 'logs' | 'spans', records: LogRecord[]): Map<string, number> {
    const rules = DEFAULT_METRIC_RULES[source]
    const tallies = createBatchTallies()
    tallyRecords(rules, records, tallies, NOW_MS)
    const counts = new Map<string, number>()
    for (const entry of tallies.byRule.get(rules[0]!.id)?.values() ?? []) {
        counts.set(entry.labelValues.join('|'), entry.count)
    }
    return counts
}

describe('default metric rules', () => {
    it('names every default metric under the reserved posthog. prefix so it cannot clash with a team rule', () => {
        for (const rule of [...DEFAULT_METRIC_RULES.spans, ...DEFAULT_METRIC_RULES.logs]) {
            expect(rule.metricName.startsWith('posthog.')).toBe(true)
        }
    })

    it('tallies server, client, producer and consumer spans by service, kind, name and status', () => {
        const counts = tallyDefaults('spans', [
            spanRecord(),
            spanRecord({ status_code: 2 }),
            spanRecord({ kind: 3, name: 'SELECT orders' }),
            spanRecord({ kind: 4, name: 'publish events' }),
            spanRecord({ kind: 5, name: 'consume events' }),
        ])
        expect(Object.fromEntries(counts)).toEqual({
            'api|SERVER|GET /checkout|OK': 1,
            'api|SERVER|GET /checkout|ERROR': 1,
            'api|CLIENT|SELECT orders|OK': 1,
            'api|PRODUCER|publish events|OK': 1,
            'api|CONSUMER|consume events|OK': 1,
        })
    })

    it('skips internal spans, whose names are the most numerous and least useful as series', () => {
        expect(tallyDefaults('spans', [spanRecord({ kind: 1, name: 'render' })]).size).toBe(0)
    })

    it('counts every log record by service and severity', () => {
        const counts = tallyDefaults('logs', [
            logRecord(),
            logRecord(),
            logRecord({ severity_text: 'INFO' }),
            logRecord({ service_name: 'web', severity_text: 'INFO' }),
        ])
        expect(Object.fromEntries(counts)).toEqual({ 'api|ERROR': 2, 'api|INFO': 1, 'web|INFO': 1 })
    })

    describe('withDefaultMetricRules', () => {
        const userRule: CompiledMetricRule = {
            id: 'user-rule',
            metricName: 'checkout.errors',
            source: 'logs',
            filterGroup: null,
            valueAttribute: null,
            groupBy: [],
        }

        it('appends the defaults for the source after the team rules', () => {
            expect(withDefaultMetricRules([userRule], 'logs')).toEqual([userRule, ...DEFAULT_METRIC_RULES.logs])
        })

        it('lets a team rule with the same metric name win over the default', () => {
            const shadowing = { ...userRule, metricName: DEFAULT_METRIC_RULES.logs[0]!.metricName }
            expect(withDefaultMetricRules([shadowing], 'logs')).toEqual([shadowing])
        })
    })
})

import type { LogRecord } from '../log-record-avro'
import { type MetricRuleRow, compileMetricRules } from './compile-metric-rules'
import { MAX_LABEL_SETS_PER_RULE, MAX_LABEL_VALUE_LENGTH, createBatchTallies, tallyRecords } from './tally'

const NOW_MS = 1_700_000_000_000

const record = (overrides: Partial<LogRecord> = {}): LogRecord => ({
    uuid: null,
    trace_id: null,
    span_id: null,
    trace_flags: null,
    timestamp: NOW_MS * 1000, // avro timestamp-micros
    observed_timestamp: null,
    body: 'hello',
    severity_text: 'ERROR',
    severity_number: 17,
    service_name: 'api',
    resource_attributes: { 'k8s.pod': 'pod-1' },
    instrumentation_scope: null,
    event_name: null,
    attributes: { 'http.status_code': '500', duration_ms: '12.5' },
    ...overrides,
})

const serviceFilterGroup = {
    type: 'AND',
    values: [
        {
            type: 'AND',
            values: [{ key: 'service.name', operator: 'exact', value: 'api', type: 'log_attribute' }],
        },
    ],
}

const ruleRow = (overrides: Partial<MetricRuleRow> = {}): MetricRuleRow => ({
    id: 'rule-1',
    metric_name: 'log.api_errors',
    filter_group: serviceFilterGroup,
    value_attribute: null,
    group_by: [],
    version: 1,
    ...overrides,
})

describe('metric rules compile + tally', () => {
    describe('compileMetricRules', () => {
        it('compiles a count rule and matches records through its filter group', () => {
            const rules = compileMetricRules([ruleRow()])
            expect(rules).toHaveLength(1)
            expect(rules[0]!.metricName).toBe('log.api_errors')
            expect(rules[0]!.valueAttribute).toBeNull()

            const tallies = createBatchTallies()
            tallyRecords(rules, [record(), record({ service_name: 'web' })], tallies, NOW_MS)
            const entries = [...tallies.byRule.get('rule-1')!.values()]
            expect(entries).toHaveLength(1)
            expect(entries[0]!.count).toBe(1)
        })

        it('treats null filter_group as match-all', () => {
            const rules = compileMetricRules([ruleRow({ filter_group: null })])
            const tallies = createBatchTallies()
            tallyRecords(rules, [record(), record({ service_name: 'web' })], tallies, NOW_MS)
            const entries = [...tallies.byRule.get('rule-1')!.values()]
            expect(entries[0]!.count).toBe(2)
        })

        it.each([
            ['non-group shape', { key: 'service.name' }],
            ['string', 'service.name = api'],
            ['array', [serviceFilterGroup]],
        ])('skips a rule whose filter_group is unparseable (%s) instead of matching all logs', (_label, fg) => {
            const rules = compileMetricRules([ruleRow({ filter_group: fg })])
            expect(rules).toHaveLength(0)
        })

        it('normalizes a non-array group_by to no grouping', () => {
            const rules = compileMetricRules([ruleRow({ group_by: 'severity_text' as unknown })])
            expect(rules[0]!.groupBy).toEqual([])
        })
    })

    describe('tallyRecords', () => {
        it('sums the numeric value attribute and skips non-numeric values', () => {
            const rules = compileMetricRules([
                ruleRow({ value_attribute: 'attributes.duration_ms', filter_group: null }),
            ])
            const tallies = createBatchTallies()
            tallyRecords(
                rules,
                [
                    record(),
                    record({ attributes: { duration_ms: '7.5' } }),
                    record({ attributes: { duration_ms: 'not-a-number' } }),
                    record({ attributes: {} }),
                ],
                tallies,
                NOW_MS
            )
            const entries = [...tallies.byRule.get('rule-1')!.values()]
            expect(entries).toHaveLength(1)
            expect(entries[0]!.count).toBe(2)
            expect(entries[0]!.sum).toBe(20)
            expect(tallies.valueSkipped).toBe(2)
        })

        it('resolves group-by labels, using empty string for missing keys and truncating long values', () => {
            const longValue = 'x'.repeat(MAX_LABEL_VALUE_LENGTH + 50)
            const rules = compileMetricRules([
                ruleRow({
                    filter_group: null,
                    group_by: ['severity_text', 'attributes.http.status_code', 'resource_attributes.missing'],
                }),
            ])
            const tallies = createBatchTallies()
            tallyRecords(rules, [record({ severity_text: longValue })], tallies, NOW_MS)
            const entries = [...tallies.byRule.get('rule-1')!.values()]
            expect(entries[0]!.labelValues).toEqual([longValue.slice(0, MAX_LABEL_VALUE_LENGTH), '500', ''])
        })

        it('accumulates records with identical label values into one entry', () => {
            const rules = compileMetricRules([ruleRow({ filter_group: null, group_by: ['severity_text'] })])
            const tallies = createBatchTallies()
            tallyRecords(rules, [record(), record(), record({ severity_text: 'INFO' })], tallies, NOW_MS)
            const ruleTallies = tallies.byRule.get('rule-1')!
            expect(ruleTallies.size).toBe(2)
            const counts = [...ruleTallies.values()].map((e) => e.count).sort()
            expect(counts).toEqual([1, 2])
        })

        it('skips records with timestamps older than the staleness window but keeps null timestamps', () => {
            const rules = compileMetricRules([ruleRow({ filter_group: null })])
            const tallies = createBatchTallies()
            const staleMicros = (NOW_MS - 21 * 60 * 1000) * 1000
            tallyRecords(
                rules,
                [record({ timestamp: staleMicros }), record({ timestamp: null }), record()],
                tallies,
                NOW_MS
            )
            const entries = [...tallies.byRule.get('rule-1')!.values()]
            expect(entries[0]!.count).toBe(2)
        })

        it('caps distinct label sets per rule and counts the overflow', () => {
            const rules = compileMetricRules([ruleRow({ filter_group: null, group_by: ['attributes.request_id'] })])
            const tallies = createBatchTallies()
            const records = Array.from({ length: MAX_LABEL_SETS_PER_RULE + 3 }, (_, i) =>
                record({ attributes: { request_id: `req-${i}` } })
            )
            tallyRecords(rules, records, tallies, NOW_MS)
            expect(tallies.byRule.get('rule-1')!.size).toBe(MAX_LABEL_SETS_PER_RULE)
            expect(tallies.seriesOverflow.get('rule-1')).toBe(3)
        })

        it('captures an exemplar trace id from a matching record and ignores zeroed trace ids', () => {
            const rules = compileMetricRules([ruleRow({ filter_group: null })])
            const tallies = createBatchTallies()
            tallyRecords(
                rules,
                [
                    record({ trace_id: Buffer.alloc(16) }),
                    record({ trace_id: Buffer.from('0123456789abcdef0123456789abcdef', 'hex') }),
                ],
                tallies,
                NOW_MS
            )
            const entries = [...tallies.byRule.get('rule-1')!.values()]
            expect(entries[0]!.exemplarTraceId).toBe('0123456789abcdef0123456789abcdef')
        })

        // capture-logs writes trace/span ids into the log Avro as base64 TEXT of the raw
        // bytes (observed in posthog.logs32), not the bytes themselves — an exemplar built
        // from the undecoded buffer is malformed and gets filtered by the metrics ingest.
        it('decodes base64-text trace ids (the on-disk log Avro format) and ignores zeroed ones', () => {
            const rules = compileMetricRules([ruleRow({ filter_group: null })])
            const tallies = createBatchTallies()
            const rawTrace = Buffer.from('0123456789abcdef0123456789abcdef', 'hex')
            const rawSpan = Buffer.from('1122334455667788', 'hex')
            tallyRecords(
                rules,
                [
                    record({ trace_id: Buffer.from(Buffer.alloc(16).toString('base64'), 'ascii') }),
                    record({
                        trace_id: Buffer.from(rawTrace.toString('base64'), 'ascii'),
                        span_id: Buffer.from(rawSpan.toString('base64'), 'ascii'),
                    }),
                ],
                tallies,
                NOW_MS
            )
            const entries = [...tallies.byRule.get('rule-1')!.values()]
            expect(entries[0]!.exemplarTraceId).toBe('0123456789abcdef0123456789abcdef')
            expect(entries[0]!.exemplarSpanId).toBe('1122334455667788')
        })
    })
})

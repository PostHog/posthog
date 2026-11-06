import type { LogRecord } from '../log-record-avro'
import { type MetricRuleRow, compileMetricRules } from './compile-metric-rules'
import {
    DEFAULT_HISTOGRAM_BOUNDS,
    MAX_LABEL_SETS_PER_RULE,
    MAX_LABEL_VALUE_LENGTH,
    MetricSeriesAdmission,
    OVERFLOW_LABEL_KEY,
    createBatchTallies,
    tallyRecords,
} from './tally'

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

        it('decodes JSON-encoded attribute values for value_attribute sums', () => {
            // Attribute values arrive JSON-encoded from capture: a numeric string
            // attribute is `'"7.5"'` on the wire. parseFloat over the raw value is
            // NaN, so without decoding the record is silently skipped.
            const rules = compileMetricRules([
                ruleRow({ value_attribute: 'attributes.duration_ms', filter_group: null }),
            ])
            const tallies = createBatchTallies()
            tallyRecords(rules, [record({ attributes: { duration_ms: '"7.5"' } })], tallies, NOW_MS)
            const entries = [...tallies.byRule.get('rule-1')!.values()]
            expect(entries[0]!.count).toBe(1)
            expect(entries[0]!.sum).toBe(7.5)
            expect(tallies.valueSkipped).toBe(0)
        })

        it('decodes JSON-encoded attribute values for group-by labels', () => {
            const rules = compileMetricRules([
                ruleRow({ filter_group: null, group_by: ['resource_attributes.k8s.pod'] }),
            ])
            const tallies = createBatchTallies()
            tallyRecords(rules, [record({ resource_attributes: { 'k8s.pod': '"pod-1"' } })], tallies, NOW_MS)
            const entries = [...tallies.byRule.get('rule-1')!.values()]
            expect(entries[0]!.labelValues).toEqual(['pod-1'])
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

        it('folds label sets past the cap into one overflow series instead of dropping them', () => {
            const rules = compileMetricRules([ruleRow({ filter_group: null, group_by: ['attributes.request_id'] })])
            const tallies = createBatchTallies()
            const records = Array.from({ length: MAX_LABEL_SETS_PER_RULE + 3 }, (_, i) =>
                record({ attributes: { request_id: `req-${i}` } })
            )
            tallyRecords(rules, records, tallies, NOW_MS)
            const ruleTallies = tallies.byRule.get('rule-1')!
            expect(ruleTallies.size).toBe(MAX_LABEL_SETS_PER_RULE + 1)
            const overflow = ruleTallies.get(OVERFLOW_LABEL_KEY)!
            expect(overflow.overflow).toBe(true)
            expect(overflow.count).toBe(3)
            expect(tallies.seriesOverflow.get('rule-1')).toBe(3)
        })

        it('keeps known label sets on their own series after the cap is reached', () => {
            const rules = compileMetricRules([ruleRow({ filter_group: null, group_by: ['attributes.request_id'] })])
            const tallies = createBatchTallies()
            const records = Array.from({ length: MAX_LABEL_SETS_PER_RULE + 1 }, (_, i) =>
                record({ attributes: { request_id: `req-${i}` } })
            )
            records.push(record({ attributes: { request_id: 'req-0' } }))
            tallyRecords(rules, records, tallies, NOW_MS)
            const ruleTallies = tallies.byRule.get('rule-1')!
            expect(ruleTallies.get(JSON.stringify(['req-0']))!.count).toBe(2)
            expect(ruleTallies.get(OVERFLOW_LABEL_KEY)!.count).toBe(1)
        })

        it('bounds label sets per rule across batches until the hour changes', () => {
            const rules = compileMetricRules([ruleRow({ filter_group: null, group_by: ['attributes.request_id'] })])
            const admission = new MetricSeriesAdmission()
            const tallyBatch = (ids: string[], nowMs: number): Map<string, { count: number }> => {
                const tallies = createBatchTallies()
                const records = ids.map((id) => record({ attributes: { request_id: id }, timestamp: nowMs * 1000 }))
                tallyRecords(rules, records, tallies, nowMs, (ruleId, labelKey) =>
                    admission.admit(1, ruleId, labelKey, nowMs)
                )
                return tallies.byRule.get('rule-1')!
            }
            tallyBatch(
                Array.from({ length: MAX_LABEL_SETS_PER_RULE }, (_, i) => `req-${i}`),
                NOW_MS
            )

            const sameHour = tallyBatch(['req-0', 'req-new'], NOW_MS + 1000)
            expect(sameHour.get(JSON.stringify(['req-0']))!.count).toBe(1)
            expect(sameHour.get(JSON.stringify(['req-new']))).toBeUndefined()
            expect(sameHour.get(OVERFLOW_LABEL_KEY)!.count).toBe(1)

            const nextHour = tallyBatch(['req-new'], NOW_MS + 60 * 60 * 1000)
            expect(nextHour.get(JSON.stringify(['req-new']))!.count).toBe(1)
        })

        it('counts colliding label sets separately, so crafted FNV-1a collisions cannot pass the cap', () => {
            const admission = new MetricSeriesAdmission(1)
            expect(admission.admit(1, 'rule-a', 'costarring', NOW_MS)).toBe(true)
            expect(admission.admit(1, 'rule-a', 'liquid', NOW_MS)).toBe(false)
        })

        it('caps a team across all its rules, so rule churn cannot take the budget of other teams', () => {
            const admission = new MetricSeriesAdmission(2, 3, 10)
            expect(admission.admit(1, 'rule-a', 'x', NOW_MS)).toBe(true)
            expect(admission.admit(1, 'rule-a', 'y', NOW_MS)).toBe(true)
            expect(admission.admit(1, 'rule-b', 'x', NOW_MS)).toBe(true)
            expect(admission.admit(1, 'rule-c', 'x', NOW_MS)).toBe(false)
            expect(admission.admit(1, 'rule-a', 'x', NOW_MS)).toBe(true)
            expect(admission.admit(2, 'rule-a', 'x', NOW_MS)).toBe(true)
        })

        it('stops admitting new label sets when the process-wide budget is spent', () => {
            const admission = new MetricSeriesAdmission(2, 2, 3)
            expect(admission.admit(1, 'rule-a', 'x', NOW_MS)).toBe(true)
            expect(admission.admit(1, 'rule-a', 'y', NOW_MS)).toBe(true)
            expect(admission.admit(2, 'rule-a', 'x', NOW_MS)).toBe(true)
            expect(admission.admit(2, 'rule-b', 'z', NOW_MS)).toBe(false)
            expect(admission.admit(2, 'rule-b', 'z', NOW_MS + 60 * 60 * 1000)).toBe(true)
        })

        it.each([
            [0, 0],
            [5, 1],
            [5.01, 2],
            [10_000, DEFAULT_HISTOGRAM_BOUNDS.length - 1],
            [10_001, DEFAULT_HISTOGRAM_BOUNDS.length],
        ])('puts value %p in histogram bucket %p (upper bound inclusive)', (value, bucket) => {
            const rules = compileMetricRules([ruleRow({ filter_group: null, value_attribute: 'attributes.v' })])
            const tallies = createBatchTallies()
            tallyRecords(rules, [record({ attributes: { v: String(value) } })], tallies, NOW_MS)
            const entry = [...tallies.byRule.get('rule-1')!.values()][0]!
            const expected = new Array(DEFAULT_HISTOGRAM_BOUNDS.length + 1).fill(0)
            expected[bucket] = 1
            expect(entry.bucketCounts).toEqual(expected)
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

import type { LogRecord } from '../log-record-avro'
import { type MetricRuleRow, compileMetricRules } from './compile-metric-rules'
import { SPAN_VALUE_DURATION_MS, createBatchTallies, tallyRecords } from './tally'

const NOW_MS = 1_700_000_000_000

/** Span-shaped record: the traces consumer decodes KafkaTraceRow through the same
 * Avro path, so a span arrives as a LogRecord carrying `name`, `kind`, `status_code`
 * and an `end_time` after `timestamp` (both Avro timestamp-micros). */
const spanRecord = (overrides: Record<string, unknown> = {}): LogRecord =>
    ({
        uuid: null,
        trace_id: null,
        span_id: null,
        trace_flags: null,
        timestamp: NOW_MS * 1000, // start, avro micros
        end_time: NOW_MS * 1000 + 250_000, // start + 250ms
        observed_timestamp: null,
        body: null,
        severity_text: null,
        severity_number: null,
        service_name: 'api',
        resource_attributes: { 'k8s.pod': 'pod-1' },
        instrumentation_scope: null,
        event_name: null,
        attributes: { 'http.status_code': '200', 'http.route': '/checkout' },
        name: 'GET /checkout',
        kind: 2, // SERVER
        status_code: 2, // ERROR
        status_message: 'boom',
        ...overrides,
    }) as unknown as LogRecord

const errorSpansFilter = {
    type: 'AND',
    values: [
        {
            type: 'AND',
            values: [{ key: 'status_code', operator: 'exact', value: '2', type: 'span_attribute' }],
        },
    ],
}

const spanRuleRow = (overrides: Partial<MetricRuleRow> = {}): MetricRuleRow => ({
    id: 'span-rule-1',
    metric_name: 'span.errors',
    source: 'spans',
    filter_group: errorSpansFilter,
    value_attribute: null,
    group_by: [],
    version: 1,
    ...overrides,
})

describe('span-based metric rules', () => {
    describe('compileMetricRules', () => {
        it('keeps a span rule and tags it with source spans', () => {
            const rules = compileMetricRules([spanRuleRow()])
            expect(rules).toHaveLength(1)
            expect(rules[0]!.source).toBe('spans')
        })

        it('defaults a rule without a source to logs', () => {
            const rules = compileMetricRules([spanRuleRow({ source: undefined })])
            expect(rules[0]!.source).toBe('logs')
        })

        it('rejects a span rule with an unknown top-level group-by key', () => {
            // severity_text is a log-only top-level key; spans do not carry it.
            const rules = compileMetricRules([spanRuleRow({ group_by: ['severity_text'] })])
            expect(rules).toHaveLength(0)
        })

        it('accepts span top-level group-by keys', () => {
            const rules = compileMetricRules([spanRuleRow({ group_by: ['name', 'status_code', 'service_name'] })])
            expect(rules).toHaveLength(1)
            expect(rules[0]!.groupBy).toEqual(['name', 'status_code', 'service_name'])
        })

        it.each([['name'], ['status_code']])('rejects a log rule grouping by span-only key %s', (key) => {
            const rules = compileMetricRules([spanRuleRow({ source: 'logs', group_by: [key] })])
            expect(rules).toHaveLength(0)
        })

        it('rejects a log rule aggregating the duration_ms span pseudo-key', () => {
            const rules = compileMetricRules([spanRuleRow({ source: 'logs', value_attribute: SPAN_VALUE_DURATION_MS })])
            expect(rules).toHaveLength(0)
        })

        it('partitions a mixed rule set by record source', () => {
            const rules = compileMetricRules([spanRuleRow(), spanRuleRow({ id: 'log-rule-1', source: 'logs' })])
            expect(rules.filter((r) => r.source === 'spans').map((r) => r.id)).toEqual(['span-rule-1'])
            expect(rules.filter((r) => r.source === 'logs').map((r) => r.id)).toEqual(['log-rule-1'])
        })
    })

    describe('tallyRecords for spans', () => {
        it('counts matching spans via a span filter group', () => {
            const rules = compileMetricRules([spanRuleRow()])
            const tallies = createBatchTallies()
            tallyRecords(rules, [spanRecord(), spanRecord({ status_code: 1 })], tallies, NOW_MS)
            const entries = [...tallies.byRule.get('span-rule-1')!.values()]
            expect(entries).toHaveLength(1)
            expect(entries[0]!.count).toBe(1) // only the ERROR span matched
        })

        it('aggregates span duration via the duration_ms pseudo-key', () => {
            const rules = compileMetricRules([spanRuleRow({ value_attribute: SPAN_VALUE_DURATION_MS })])
            const tallies = createBatchTallies()
            tallyRecords(rules, [spanRecord()], tallies, NOW_MS)
            const entries = [...tallies.byRule.get('span-rule-1')!.values()]
            expect(entries[0]!.sum).toBe(250) // end_time - timestamp = 250ms
        })

        it('resolves span top-level group-by keys from the record', () => {
            const rules = compileMetricRules([spanRuleRow({ group_by: ['name', 'status_code'] })])
            const tallies = createBatchTallies()
            tallyRecords(rules, [spanRecord()], tallies, NOW_MS)
            const entries = [...tallies.byRule.get('span-rule-1')!.values()]
            expect(entries[0]!.labelValues).toEqual(['GET /checkout', 'ERROR'])
        })

        it('labels status_code with the OTel enum name, falling back to the raw value for unknown codes', () => {
            const rules = compileMetricRules([spanRuleRow({ filter_group: null, group_by: ['status_code'] })])
            const tallies = createBatchTallies()
            tallyRecords(
                rules,
                [spanRecord({ status_code: 0 }), spanRecord({ status_code: 1 }), spanRecord({ status_code: 99 })],
                tallies,
                NOW_MS
            )
            const labels = [...tallies.byRule.get('span-rule-1')!.values()].map((e) => e.labelValues[0])
            expect(labels).toEqual(['UNSET', 'OK', '99'])
        })

        it('accepts kind as a span group-by key and labels it with the OTel kind name', () => {
            const rules = compileMetricRules([spanRuleRow({ filter_group: null, group_by: ['kind'] })])
            expect(rules).toHaveLength(1)
            const tallies = createBatchTallies()
            tallyRecords(rules, [spanRecord({ kind: 2 }), spanRecord({ kind: 3 })], tallies, NOW_MS)
            const labels = [...tallies.byRule.get('span-rule-1')!.values()].map((e) => e.labelValues[0])
            expect(labels).toEqual(['SERVER', 'CLIENT'])
        })

        it('measures staleness from end_time, so a long-running span that just ended still tallies', () => {
            // A 25-minute batch-job span: start is older than MAX_RECORD_AGE_MS but the span
            // ended just now. Gating on start time would drop it and truncate the latency
            // tail a duration_ms rule exists to show.
            const rules = compileMetricRules([spanRuleRow({ value_attribute: SPAN_VALUE_DURATION_MS })])
            const tallies = createBatchTallies()
            tallyRecords(
                rules,
                [spanRecord({ timestamp: (NOW_MS - 25 * 60 * 1000) * 1000, end_time: NOW_MS * 1000 })],
                tallies,
                NOW_MS
            )
            const entries = [...tallies.byRule.get('span-rule-1')!.values()]
            expect(entries).toHaveLength(1)
        })

        it('still drops a replayed span whose end_time is older than the staleness window', () => {
            const rules = compileMetricRules([spanRuleRow()])
            const tallies = createBatchTallies()
            tallyRecords(
                rules,
                [
                    spanRecord({
                        timestamp: (NOW_MS - 60 * 60 * 1000) * 1000,
                        end_time: (NOW_MS - 30 * 60 * 1000) * 1000,
                    }),
                ],
                tallies,
                NOW_MS
            )
            expect(tallies.byRule.get('span-rule-1')).toBeUndefined()
        })
    })
})

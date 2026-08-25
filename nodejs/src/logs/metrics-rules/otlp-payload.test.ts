import type { LogRecord } from '../log-record-avro'
import { compileMetricRules } from './compile-metric-rules'
import { buildMetricRulesOtlpPayload } from './otlp-payload'
import { createBatchTallies, tallyRecords } from './tally'

const NOW_MS = 1_700_000_000_123
// Snapped down to the enclosing 10s bucket, in nanos.
const SNAPPED_NANOS = '1700000000000000000'

const record = (overrides: Partial<LogRecord> = {}): LogRecord => ({
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
    attributes: { duration_ms: '12.5' },
    ...overrides,
})

const countRule = {
    id: 'rule-count',
    metric_name: 'log.api_errors',
    filter_group: null,
    value_attribute: null,
    group_by: ['severity_text'],
}

const distributionRule = {
    id: 'rule-dist',
    metric_name: 'log.request_duration',
    filter_group: null,
    value_attribute: 'attributes.duration_ms',
    group_by: [],
}

function build(rows: any[], records: LogRecord[]): any {
    const rules = compileMetricRules(rows)
    const tallies = createBatchTallies()
    tallyRecords(rules, records, tallies, NOW_MS)
    return buildMetricRulesOtlpPayload(rules, tallies, NOW_MS)
}

describe('buildMetricRulesOtlpPayload', () => {
    it('returns null when nothing was tallied', () => {
        expect(build([countRule], [])).toBeNull()
    })

    it('emits a count rule as a delta monotonic sum with 10s-snapped timestamps', () => {
        const payload = build([countRule], [record(), record(), record({ severity_text: 'INFO' })])
        const metrics = payload.resourceMetrics[0].scopeMetrics[0].metrics
        expect(metrics).toHaveLength(1)
        const sum = metrics[0].sum
        expect(metrics[0].name).toBe('log.api_errors')
        expect(sum.aggregationTemporality).toBe(1)
        expect(sum.isMonotonic).toBe(true)
        expect(sum.dataPoints).toHaveLength(2)

        const errorPoint = sum.dataPoints.find((dp: any) => dp.attributes[0].value.stringValue === 'ERROR')
        expect(errorPoint.attributes).toEqual([{ key: 'severity_text', value: { stringValue: 'ERROR' } }])
        expect(errorPoint.asDouble).toBe(2)
        expect(errorPoint.timeUnixNano).toBe(SNAPPED_NANOS)
    })

    it('emits a value-attribute rule as a delta histogram carrying count and sum', () => {
        const payload = build([distributionRule], [record(), record({ attributes: { duration_ms: '7.5' } })])
        const metric = payload.resourceMetrics[0].scopeMetrics[0].metrics[0]
        expect(metric.name).toBe('log.request_duration')
        expect(metric.histogram.aggregationTemporality).toBe(1)
        const dp = metric.histogram.dataPoints[0]
        expect(dp.count).toBe(2)
        expect(dp.sum).toBe(20)
        expect(dp.explicitBounds).toEqual([])
        expect(dp.bucketCounts).toEqual([2])
        expect(dp.timeUnixNano).toBe(SNAPPED_NANOS)
    })

    it('strips the attributes. prefix from group-by label names', () => {
        const payload = build(
            [{ ...countRule, group_by: ['attributes.http.status_code'] }],
            [record({ attributes: { 'http.status_code': '500' } })]
        )
        const dp = payload.resourceMetrics[0].scopeMetrics[0].metrics[0].sum.dataPoints[0]
        expect(dp.attributes).toEqual([{ key: 'http.status_code', value: { stringValue: '500' } }])
    })

    it('partitions service_name group-bys into per-service resource blocks with service.name', () => {
        const payload = build(
            [{ ...countRule, group_by: ['service_name'] }],
            [record(), record({ service_name: 'web' })]
        )
        expect(payload.resourceMetrics).toHaveLength(2)
        const services = payload.resourceMetrics
            .map((rm: any) => rm.resource.attributes[0])
            .map((attr: any) => {
                expect(attr.key).toBe('service.name')
                return attr.value.stringValue
            })
            .sort()
        expect(services).toEqual(['api', 'web'])
        for (const rm of payload.resourceMetrics) {
            const dp = rm.scopeMetrics[0].metrics[0].sum.dataPoints[0]
            expect(dp.asDouble).toBe(1)
            // service is carried on the resource, not duplicated as a data-point attribute
            expect(dp.attributes).toEqual([])
        }
    })

    it('attaches an exemplar with the matching record trace id', () => {
        const payload = build(
            [countRule],
            [record({ trace_id: Buffer.from('0123456789abcdef0123456789abcdef', 'hex') })]
        )
        const dp = payload.resourceMetrics[0].scopeMetrics[0].metrics[0].sum.dataPoints[0]
        expect(dp.exemplars).toHaveLength(1)
        expect(dp.exemplars[0].traceId).toBe('0123456789abcdef0123456789abcdef')
    })
})

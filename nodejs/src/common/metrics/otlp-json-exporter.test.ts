import { context, propagation, trace } from '@opentelemetry/api'
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics'
import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import { counterWithExemplars, histogramWithExemplars, resetExemplarsForTests } from './exemplars'
import { OtlpJsonMetricExporter } from './otlp-json-exporter'

jest.mock('~/common/utils/request', () => ({
    ...jest.requireActual('~/common/utils/request'),
    internalFetch: jest.fn(),
}))

// The upstream OTel JS pipeline silently drops exemplars end to end: the SDK never
// samples them and otlp-transformer never serializes them. This exporter is the only
// thing standing between us and exemplar-less metrics — these tests guard both the
// exemplar attachment and the OTLP/JSON wire shape capture-logs parses (hex trace ids,
// camelCase fields, stringified unix nanos).
describe('OtlpJsonMetricExporter', () => {
    let provider: MeterProvider
    let reader: PeriodicExportingMetricReader
    let tracerProvider: NodeTracerProvider
    const fetchMock = jest.mocked(internalFetch)

    beforeEach(() => {
        resetExemplarsForTests()
        fetchMock.mockReset().mockResolvedValue({ status: 200, dump: () => Promise.resolve() } as any)
        reader = new PeriodicExportingMetricReader({
            exporter: new OtlpJsonMetricExporter({
                url: 'http://capture-logs.local/v1/metrics',
                headers: { Authorization: 'Bearer phc_test' },
            }),
            exportIntervalMillis: 60_000,
        })
        provider = new MeterProvider({ readers: [reader] })
        tracerProvider = new NodeTracerProvider()
        tracerProvider.register()
    })

    afterEach(async () => {
        await provider.shutdown()
        await tracerProvider.shutdown()
        trace.disable()
        context.disable()
        propagation.disable()
        jest.restoreAllMocks()
    })

    const exportedBody = (): any => {
        expect(fetchMock).toHaveBeenCalled()
        const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1]
        expect(url).toBe('http://capture-logs.local/v1/metrics')
        expect(init?.headers).toMatchObject({
            Authorization: 'Bearer phc_test',
            'Content-Type': 'application/json',
        })
        return parseJSON(init?.body as string)
    }

    const metricsByName = (body: any): Record<string, any> => {
        const out: Record<string, any> = {}
        for (const rm of body.resourceMetrics) {
            for (const sm of rm.scopeMetrics) {
                for (const metric of sm.metrics) {
                    out[metric.name] = metric
                }
            }
        }
        return out
    }

    it('serializes counters and histograms with exemplars from the active span', async () => {
        const meter = provider.getMeter('test-meter')
        const counter = counterWithExemplars('records_dropped_total', meter.createCounter('records_dropped_total'))
        const histogram = histogramWithExemplars(
            'processing_seconds',
            meter.createHistogram('processing_seconds', {
                advice: { explicitBucketBoundaries: [0.01, 0.1, 1] },
            })
        )

        let traceIdHex = ''
        let spanIdHex = ''
        trace.getTracer('test').startActiveSpan('handleEachBatch', (span) => {
            traceIdHex = span.spanContext().traceId
            spanIdHex = span.spanContext().spanId
            counter.add(7, { team_id: '42' })
            histogram.record(0.05, { codec: 'gzip' })
            span.end()
        })

        await reader.forceFlush()
        const metrics = metricsByName(exportedBody())

        const sumPoint = metrics['records_dropped_total'].sum.dataPoints[0]
        expect(metrics['records_dropped_total'].sum.isMonotonic).toBe(true)
        expect(metrics['records_dropped_total'].sum.aggregationTemporality).toBe(2)
        expect(sumPoint.asDouble).toBe(7)
        expect(sumPoint.attributes).toEqual([{ key: 'team_id', value: { stringValue: '42' } }])
        expect(sumPoint.timeUnixNano).toMatch(/^\d+$/)
        expect(sumPoint.exemplars).toEqual([
            expect.objectContaining({ asDouble: 7, traceId: traceIdHex, spanId: spanIdHex }),
        ])

        const histPoint = metrics['processing_seconds'].histogram.dataPoints[0]
        expect(metrics['processing_seconds'].histogram.aggregationTemporality).toBe(2)
        expect(histPoint.count).toBe(1)
        expect(histPoint.sum).toBeCloseTo(0.05)
        expect(histPoint.explicitBounds).toEqual([0.01, 0.1, 1])
        expect(histPoint.bucketCounts).toEqual([0, 1, 0, 0])
        expect(histPoint.exemplars).toEqual([
            expect.objectContaining({ asDouble: 0.05, traceId: traceIdHex, spanId: spanIdHex }),
        ])
    })

    it('omits exemplars for measurements recorded outside any span', async () => {
        const meter = provider.getMeter('test-meter')
        const counter = counterWithExemplars('records_received_total', meter.createCounter('records_received_total'))

        counter.add(3)

        await reader.forceFlush()
        const metrics = metricsByName(exportedBody())
        const point = metrics['records_received_total'].sum.dataPoints[0]
        expect(point.asDouble).toBe(3)
        expect(point.exemplars).toBeUndefined()
    })

    it.each([
        ['a rejected request', () => fetchMock.mockRejectedValueOnce(new Error('connect ECONNREFUSED'))],
        [
            'a non-2xx response',
            () => fetchMock.mockResolvedValueOnce({ status: 503, dump: () => Promise.resolve() } as any),
        ],
    ])('re-buffers exemplars after %s so the next export still carries them', async (_name, primeFailure) => {
        primeFailure()
        const meter = provider.getMeter('test-meter')
        const counter = counterWithExemplars('records_dropped_total', meter.createCounter('records_dropped_total'))

        let traceIdHex = ''
        trace.getTracer('test').startActiveSpan('batch', (span) => {
            traceIdHex = span.spanContext().traceId
            counter.add(5, { team_id: '42' })
            span.end()
        })

        await reader.forceFlush().catch(() => {}) // failed export
        await reader.forceFlush() // retried export succeeds

        const metrics = metricsByName(exportedBody())
        const point = metrics['records_dropped_total'].sum.dataPoints[0]
        expect(point.exemplars).toEqual([expect.objectContaining({ asDouble: 5, traceId: traceIdHex })])
    })

    it('an exemplar matches only the data point series it was recorded against', async () => {
        const meter = provider.getMeter('test-meter')
        const counter = counterWithExemplars('records_dropped_total', meter.createCounter('records_dropped_total'))

        counter.add(1, { team_id: '1' })
        trace.getTracer('test').startActiveSpan('batch', (span) => {
            counter.add(2, { team_id: '2' })
            span.end()
        })

        await reader.forceFlush()
        const metrics = metricsByName(exportedBody())
        const points = metrics['records_dropped_total'].sum.dataPoints
        const byTeam = Object.fromEntries(points.map((p: any) => [p.attributes[0].value.stringValue, p]))
        expect(byTeam['1'].exemplars).toBeUndefined()
        expect(byTeam['2'].exemplars).toHaveLength(1)
    })
})

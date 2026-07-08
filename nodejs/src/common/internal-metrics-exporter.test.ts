import { Counter, Gauge, Histogram, Registry } from 'prom-client'

import { parseJSON } from '~/common/utils/json-parse'

import {
    InternalMetricsExporter,
    buildOtlpMetricsPayload,
    internalMetricsConfigFromEnv,
} from './internal-metrics-exporter'

describe('internal-metrics-exporter', () => {
    let registry: Registry

    beforeEach(() => {
        registry = new Registry()
    })

    describe('buildOtlpMetricsPayload', () => {
        const build = async (): Promise<ReturnType<typeof buildOtlpMetricsPayload>> =>
            buildOtlpMetricsPayload(await registry.getMetricsAsJSON(), {
                serviceName: 'test-service',
                startTimeMs: 1700000000000,
                nowMs: 1700000060000,
            })

        it('converts counters to cumulative monotonic sums with label attributes', async () => {
            const counter = new Counter({
                name: 'orders_total',
                help: 'orders',
                labelNames: ['plan'],
                registers: [registry],
            })
            counter.inc({ plan: 'free' }, 3)
            counter.inc({ plan: 'pro' }, 5)

            const payload = await build()
            const metric = payload!.resourceMetrics[0].scopeMetrics[0].metrics[0]
            expect(metric.name).toBe('orders_total')
            expect(metric.sum.aggregationTemporality).toBe(2)
            expect(metric.sum.isMonotonic).toBe(true)
            const points = metric.sum.dataPoints
            expect(points).toHaveLength(2)
            const byPlan = Object.fromEntries(
                points.map((p: any) => [p.attributes.find((a: any) => a.key === 'plan').value.stringValue, p.asDouble])
            )
            expect(byPlan).toEqual({ free: 3, pro: 5 })
            expect(points[0].startTimeUnixNano).toBe('1700000000000000000')
            expect(points[0].timeUnixNano).toBe('1700000060000000000')
        })

        it('converts gauges to gauge data points', async () => {
            const gauge = new Gauge({ name: 'queue_depth', help: 'depth', registers: [registry] })
            gauge.set(17)

            const payload = await build()
            const metric = payload!.resourceMetrics[0].scopeMetrics[0].metrics[0]
            expect(metric.gauge.dataPoints[0].asDouble).toBe(17)
        })

        it('converts histograms: cumulative le buckets become per-bucket counts, +Inf becomes the overflow bucket', async () => {
            const hist = new Histogram({
                name: 'latency_ms',
                help: 'latency',
                buckets: [10, 50, 100],
                registers: [registry],
            })
            hist.observe(5) // le=10
            hist.observe(40) // le=50
            hist.observe(45) // le=50
            hist.observe(2000) // +Inf overflow

            const payload = await build()
            const metric = payload!.resourceMetrics[0].scopeMetrics[0].metrics[0]
            const dp = metric.histogram.dataPoints[0]
            expect(metric.histogram.aggregationTemporality).toBe(2)
            expect(dp.explicitBounds).toEqual([10, 50, 100])
            expect(dp.bucketCounts).toEqual([1, 2, 0, 1])
            expect(dp.count).toBe(4)
            expect(dp.sum).toBeCloseTo(5 + 40 + 45 + 2000)
        })

        it('splits histogram label sets into separate data points', async () => {
            const hist = new Histogram({
                name: 'latency_ms',
                help: 'latency',
                labelNames: ['route'],
                buckets: [10],
                registers: [registry],
            })
            hist.observe({ route: '/a' }, 5)
            hist.observe({ route: '/b' }, 20)

            const payload = await build()
            const dps = payload!.resourceMetrics[0].scopeMetrics[0].metrics[0].histogram.dataPoints
            expect(dps).toHaveLength(2)
            const byRoute = Object.fromEntries(
                dps.map((p: any) => [
                    p.attributes.find((a: any) => a.key === 'route').value.stringValue,
                    p.bucketCounts,
                ])
            )
            expect(byRoute).toEqual({ '/a': [1, 0], '/b': [0, 1] })
        })

        it('attaches service.name as a resource attribute and returns null when there are no metrics', async () => {
            expect(await build()).toBeNull()

            new Gauge({ name: 'g', help: 'g', registers: [registry] }).set(1)
            const payload = await build()
            expect(payload!.resourceMetrics[0].resource.attributes).toContainEqual({
                key: 'service.name',
                value: { stringValue: 'test-service' },
            })
        })
    })

    describe('InternalMetricsExporter', () => {
        beforeEach(() => {
            jest.useFakeTimers()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('posts the registry as OTLP JSON on the configured interval', async () => {
            const gauge = new Gauge({ name: 'depth', help: 'depth', registers: [registry] })
            gauge.set(42)
            const fetchMock = jest.fn().mockResolvedValue({ status: 200 })

            const exporter = new InternalMetricsExporter(
                { host: 'https://us.i.posthog.com', token: 'phc_test', intervalSeconds: 15, serviceName: 'svc' },
                registry,
                fetchMock as any
            )
            exporter.start()

            await jest.advanceTimersByTimeAsync(15000)
            expect(fetchMock).toHaveBeenCalledTimes(1)
            const [url, init] = fetchMock.mock.calls[0]
            expect(url).toBe('https://us.i.posthog.com/i/v1/metrics?token=phc_test')
            expect(init.method).toBe('POST')
            const body = parseJSON(init.body)
            expect(body.resourceMetrics[0].scopeMetrics[0].metrics[0].name).toBe('depth')

            await jest.advanceTimersByTimeAsync(15000)
            expect(fetchMock).toHaveBeenCalledTimes(2)

            exporter.stop()
            await jest.advanceTimersByTimeAsync(60000)
            expect(fetchMock).toHaveBeenCalledTimes(2)
        })

        it('survives fetch failures and keeps exporting', async () => {
            new Gauge({ name: 'depth', help: 'depth', registers: [registry] }).set(1)
            const fetchMock = jest.fn().mockRejectedValue(new Error('offline'))

            const exporter = new InternalMetricsExporter(
                { host: 'https://us.i.posthog.com', token: 'phc_test', intervalSeconds: 15, serviceName: 'svc' },
                registry,
                fetchMock as any
            )
            exporter.start()
            await jest.advanceTimersByTimeAsync(30000)
            expect(fetchMock).toHaveBeenCalledTimes(2)
            exporter.stop()
        })
    })

    describe('internalMetricsConfigFromEnv', () => {
        it('is disabled without a token and enabled with one', () => {
            expect(internalMetricsConfigFromEnv({})).toBeNull()

            const config = internalMetricsConfigFromEnv({
                POSTHOG_INTERNAL_METRICS_TOKEN: 'phc_x',
                POSTHOG_INTERNAL_METRICS_HOST: 'https://us.i.posthog.com',
                POSTHOG_INTERNAL_METRICS_SERVICE_NAME: 'plugin-server',
                POSTHOG_INTERNAL_METRICS_INTERVAL_SECONDS: '30',
            })
            expect(config).toEqual({
                token: 'phc_x',
                host: 'https://us.i.posthog.com',
                serviceName: 'plugin-server',
                intervalSeconds: 30,
            })
        })
    })
})

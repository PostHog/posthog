import { metrics as metricsApi } from '@opentelemetry/api'
import {
    DataPointType,
    InMemoryMetricExporter,
    MeterProvider,
    type MetricData,
    PeriodicExportingMetricReader,
} from '@opentelemetry/sdk-metrics'

import { cpuUsageSeconds, registerProcessOtelMetrics, resetProcessOtelMetricsForTests } from './process-otel-metrics'

describe('process-otel-metrics', () => {
    it('converts cumulative microsecond CPU usage to seconds', () => {
        expect(cpuUsageSeconds({ user: 2_500_000, system: 500_000 })).toEqual(3)
    })

    describe('registered observables', () => {
        let exporter: InMemoryMetricExporter
        let provider: MeterProvider
        let reader: PeriodicExportingMetricReader

        beforeEach(() => {
            exporter = new InMemoryMetricExporter(0)
            reader = new PeriodicExportingMetricReader({ exporter, exportIntervalMillis: 60_000 })
            provider = new MeterProvider({ readers: [reader] })
            metricsApi.setGlobalMeterProvider(provider)
            resetProcessOtelMetricsForTests()
        })

        afterEach(async () => {
            await provider.shutdown()
            metricsApi.disable()
        })

        const metricFor = (name: string): MetricData | undefined =>
            exporter
                .getMetrics()
                .flatMap((rm) => rm.scopeMetrics)
                .flatMap((sm) => sm.metrics)
                .find((m) => m.descriptor.name === name)

        it('observes CPU seconds as a monotonic sum and RSS / event loop utilization as gauges', async () => {
            registerProcessOtelMetrics()

            await reader.forceFlush()

            const cpu = metricFor('process_cpu_seconds_total')
            expect(cpu?.dataPointType).toEqual(DataPointType.SUM)
            expect(cpu && 'isMonotonic' in cpu && cpu.isMonotonic).toBe(true)
            expect(cpu?.dataPoints[0].value as number).toBeGreaterThan(0)
            // A µs→s conversion slip reads as ~1e6× the process's real CPU time.
            expect(cpu?.dataPoints[0].value as number).toBeLessThan(process.uptime() * 64)

            const rss = metricFor('process_resident_memory_bytes')
            expect(rss?.dataPointType).toEqual(DataPointType.GAUGE)
            expect(rss?.dataPoints[0].value as number).toBeGreaterThan(0)

            const elu = metricFor('event_loop_utilization')
            expect(elu?.dataPointType).toEqual(DataPointType.GAUGE)
            expect(elu?.dataPoints[0].value as number).toBeGreaterThanOrEqual(0)
            expect(elu?.dataPoints[0].value as number).toBeLessThanOrEqual(1)
        })

        it('is idempotent: re-registering does not create duplicate series', async () => {
            registerProcessOtelMetrics()
            registerProcessOtelMetrics()

            await reader.forceFlush()

            const cpu = metricFor('process_cpu_seconds_total')
            expect(cpu?.dataPoints).toHaveLength(1)
        })
    })
})

import { metrics as metricsApi } from '@opentelemetry/api'
import {
    type DataPoint,
    InMemoryMetricExporter,
    MeterProvider,
    PeriodicExportingMetricReader,
} from '@opentelemetry/sdk-metrics'

import { recordMetricsIngested, resetMetricsIngestionInstrumentsForTests } from './ingestion-otel-metrics'

describe('ingestion-otel-metrics', () => {
    let exporter: InMemoryMetricExporter
    let provider: MeterProvider
    let reader: PeriodicExportingMetricReader

    beforeEach(() => {
        // Simulate the real startup-order hazard: a record call may run before a
        // provider exists (bound to the noop meter), with the provider registered
        // afterwards. Lazily acquired instruments must still deliver data recorded
        // after registration.
        resetMetricsIngestionInstrumentsForTests()
        recordMetricsIngested(1, 1, 1)

        exporter = new InMemoryMetricExporter(0)
        reader = new PeriodicExportingMetricReader({ exporter, exportIntervalMillis: 60_000 })
        provider = new MeterProvider({ readers: [reader] })
        metricsApi.setGlobalMeterProvider(provider)
        resetMetricsIngestionInstrumentsForTests()
    })

    afterEach(async () => {
        await provider.shutdown()
        metricsApi.disable()
    })

    const dataPointsFor = <T>(name: string): readonly DataPoint<T>[] =>
        exporter
            .getMetrics()
            .flatMap((rm) => rm.scopeMetrics)
            .flatMap((sm) => sm.metrics)
            .filter((m) => m.descriptor.name === name)
            .flatMap((m) => m.dataPoints as unknown as readonly DataPoint<T>[])

    it.each([
        ['bytes', 'metrics_ingestion_bytes_ingested_total', 2048],
        ['records', 'metrics_ingestion_records_ingested_total', 10],
    ] as const)('emits per-team ingested %s', async (_name, metricName, value) => {
        recordMetricsIngested(42, 2048, 10)

        await reader.forceFlush()

        const points = dataPointsFor<number>(metricName)
        expect(points).toHaveLength(1)
        expect(points[0].attributes).toEqual({ team_id: '42' })
        expect(points[0].value).toEqual(value)
    })

    it('skips zero and negative amounts so no empty per-team series are created', async () => {
        recordMetricsIngested(42, 0, 0)
        recordMetricsIngested(43, -1, 0)

        await reader.forceFlush()

        const names = ['metrics_ingestion_bytes_ingested_total', 'metrics_ingestion_records_ingested_total']
        expect(names.map((name) => dataPointsFor(name).length)).toEqual([0, 0])
    })

    it('swallows a throwing OTel SDK so the consumer background task is never rejected', () => {
        const throwing = () => {
            throw new Error('otel exploded')
        }
        metricsApi.disable() // the API ignores a second setGlobalMeterProvider without this
        metricsApi.setGlobalMeterProvider({
            getMeter: () =>
                ({
                    createCounter: () => ({ add: throwing }),
                }) as any,
        } as any)
        resetMetricsIngestionInstrumentsForTests()

        expect(() => recordMetricsIngested(42, 1, 1)).not.toThrow()
    })
})

import { metrics as metricsApi } from '@opentelemetry/api'
import {
    type DataPoint,
    InMemoryMetricExporter,
    MeterProvider,
    PeriodicExportingMetricReader,
} from '@opentelemetry/sdk-metrics'

import { recordPiiReplacements, resetPiiReplacementsCounterForTests } from './otel-metrics'

describe('otel-metrics', () => {
    let exporter: InMemoryMetricExporter
    let provider: MeterProvider
    let reader: PeriodicExportingMetricReader

    beforeEach(() => {
        // Simulate the real startup order hazard: something may call
        // recordPiiReplacements before a provider exists (bound to the noop
        // meter), and the provider is registered afterwards. The lazy counter
        // must still deliver data recorded after registration.
        resetPiiReplacementsCounterForTests()
        recordPiiReplacements('logs', 1)

        exporter = new InMemoryMetricExporter(0)
        reader = new PeriodicExportingMetricReader({ exporter, exportIntervalMillis: 60_000 })
        provider = new MeterProvider({ readers: [reader] })
        metricsApi.setGlobalMeterProvider(provider)
        resetPiiReplacementsCounterForTests()
    })

    afterEach(async () => {
        await provider.shutdown()
        metricsApi.disable()
    })

    it('records replacements with the pipeline source, skipping zero counts', async () => {
        recordPiiReplacements('logs', 3)
        recordPiiReplacements('traces', 2)
        recordPiiReplacements('logs', 0)

        await reader.forceFlush()

        const points = exporter
            .getMetrics()
            .flatMap((rm) => rm.scopeMetrics)
            .flatMap((sm) => sm.metrics)
            .filter((m) => m.descriptor.name === 'logs_pii_replacements_total')
            .flatMap((m) => m.dataPoints as readonly DataPoint<number>[])
        const bySource = Object.fromEntries(points.map((p) => [p.attributes.source, p.value]))

        expect(bySource).toEqual({ logs: 3, traces: 2 })
    })
})

import { metrics as metricsApi } from '@opentelemetry/api'
import {
    type DataPoint,
    InMemoryMetricExporter,
    MeterProvider,
    PeriodicExportingMetricReader,
} from '@opentelemetry/sdk-metrics'

import { ProducerStatsTracker } from './kafka-producer-metrics'
import { resetProducerOtelInstrumentsForTests } from './producer-otel-metrics'

const makeStats = (overrides: Record<string, any> = {}): string =>
    JSON.stringify({
        msg_cnt: 10,
        msg_size: 1024,
        msg_max: 100_000,
        msg_size_max: 1_073_741_824,
        replyq: 0,
        brokers: {},
        topics: {},
        ...overrides,
    })

describe('producer otel-metrics', () => {
    let exporter: InMemoryMetricExporter
    let provider: MeterProvider
    let reader: PeriodicExportingMetricReader

    beforeEach(() => {
        exporter = new InMemoryMetricExporter(0)
        reader = new PeriodicExportingMetricReader({ exporter, exportIntervalMillis: 60_000 })
        provider = new MeterProvider({ readers: [reader] })
        metricsApi.setGlobalMeterProvider(provider)
        resetProducerOtelInstrumentsForTests()
    })

    afterEach(async () => {
        await provider.shutdown()
        metricsApi.disable()
    })

    const dataPointsFor = (name: string): readonly DataPoint<number>[] =>
        exporter
            .getMetrics()
            .flatMap((rm) => rm.scopeMetrics)
            .flatMap((sm) => sm.metrics)
            .filter((m) => m.descriptor.name === name)
            .flatMap((m) => m.dataPoints as unknown as readonly DataPoint<number>[])

    it('mirrors queue depth and broker health gauges from a tracked librdkafka stats payload', async () => {
        const tracker = new ProducerStatsTracker('LOGS')

        tracker.track(
            makeStats({
                msg_cnt: 42,
                msg_size: 9000,
                brokers: {
                    'kafka-1:9092/1': { state: 'UP' },
                    'kafka-2:9092/2': { state: 'DOWN' },
                },
            })
        )

        await reader.forceFlush()

        const attributes = { producer_name: 'LOGS' }
        const expectations: [string, number][] = [
            ['kafka_producer_queue_messages', 42],
            ['kafka_producer_queue_bytes', 9000],
            ['kafka_producer_any_brokers_down', 1],
        ]
        for (const [name, value] of expectations) {
            const points = dataPointsFor(name)
            expect(points).toHaveLength(1)
            expect(points[0].attributes).toEqual(attributes)
            expect(points[0].value).toEqual(value)
        }
    })

    it('swallows a throwing OTel SDK so stats callbacks never break the producer', () => {
        const throwing = () => {
            throw new Error('otel exploded')
        }
        metricsApi.disable() // the API ignores a second setGlobalMeterProvider without this
        metricsApi.setGlobalMeterProvider({
            getMeter: () => ({ createGauge: () => ({ record: throwing }) }) as any,
        } as any)
        resetProducerOtelInstrumentsForTests()

        expect(() => new ProducerStatsTracker('LOGS').track(makeStats())).not.toThrow()
    })
})

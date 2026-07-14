import { metrics as metricsApi } from '@opentelemetry/api'
import {
    type DataPoint,
    type Histogram as HistogramDataPointValue,
    InMemoryMetricExporter,
    MeterProvider,
    PeriodicExportingMetricReader,
} from '@opentelemetry/sdk-metrics'

import { kafkaConsumerMessageAgeSeconds } from './metrics'
import {
    recordBatchConsumed,
    recordConsumedBatchBackpressure,
    recordConsumedBatchDuration,
    resetConsumerOtelInstrumentsForTests,
} from './otel-metrics'

describe('consumer otel-metrics', () => {
    let exporter: InMemoryMetricExporter
    let provider: MeterProvider
    let reader: PeriodicExportingMetricReader

    beforeEach(() => {
        // Simulate the real startup-order hazard: a record call may run before a
        // provider exists (bound to the noop meter), with the provider registered
        // afterwards. Lazily acquired instruments must still deliver data recorded
        // after registration.
        resetConsumerOtelInstrumentsForTests()
        recordConsumedBatchDuration(1, 'warmup', 'warmup')

        exporter = new InMemoryMetricExporter(0)
        reader = new PeriodicExportingMetricReader({ exporter, exportIntervalMillis: 60_000 })
        provider = new MeterProvider({ readers: [reader] })
        metricsApi.setGlobalMeterProvider(provider)
        resetConsumerOtelInstrumentsForTests()
        kafkaConsumerMessageAgeSeconds.reset()
    })

    afterEach(async () => {
        await provider.shutdown()
        metricsApi.disable()
    })

    const dataPointsFor = (name: string): readonly DataPoint<HistogramDataPointValue>[] =>
        exporter
            .getMetrics()
            .flatMap((rm) => rm.scopeMetrics)
            .flatMap((sm) => sm.metrics)
            .filter((m) => m.descriptor.name === name)
            .flatMap((m) => m.dataPoints as unknown as readonly DataPoint<HistogramDataPointValue>[])

    it('records the age of the OLDEST message in seconds, to both the OTel and prom sinks', async () => {
        const nowMs = 1_700_000_060_000
        // Oldest message is 60s old; a ms/seconds mix-up or an oldest/newest flip changes the value.
        recordBatchConsumed(
            'clickhouse_logs',
            'group-1',
            [{ timestamp: nowMs - 60_000 }, { timestamp: nowMs - 5_000 }],
            nowMs
        )

        await reader.forceFlush()

        const points = dataPointsFor('kafka_consumer_message_age_seconds')
        expect(points).toHaveLength(1)
        expect(points[0].attributes).toEqual({ topic: 'clickhouse_logs', groupId: 'group-1' })
        expect(points[0].value.count).toEqual(1)
        expect(points[0].value.sum).toBeCloseTo(60)

        const promSnapshot = await kafkaConsumerMessageAgeSeconds.get()
        const promSum = promSnapshot.values.find(
            (v) =>
                v.metricName === 'kafka_consumer_message_age_seconds_sum' &&
                v.labels.topic === 'clickhouse_logs' &&
                v.labels.groupId === 'group-1'
        )
        expect(promSum?.value).toBeCloseTo(60)
    })

    it('clamps clock skew to zero and still records batch size for empty or untimestamped batches', async () => {
        const nowMs = 1_700_000_060_000
        recordBatchConsumed('t', 'g', [{ timestamp: nowMs + 30_000 }], nowMs) // producer clock ahead
        recordBatchConsumed('t', 'g', [{}, {}], nowMs) // no timestamps
        recordBatchConsumed('t', 'g', [], nowMs) // empty poll

        await reader.forceFlush()

        const agePoints = dataPointsFor('kafka_consumer_message_age_seconds')
        expect(agePoints).toHaveLength(1)
        expect(agePoints[0].value.count).toEqual(1)
        expect(agePoints[0].value.sum).toEqual(0)

        const sizePoints = dataPointsFor('consumer_batch_size')
        expect(sizePoints).toHaveLength(1)
        expect(sizePoints[0].attributes).toEqual({})
        expect(sizePoints[0].value.count).toEqual(3)
        expect(sizePoints[0].value.sum).toEqual(3)
    })

    it.each([
        ['recordConsumedBatchDuration', 'consumed_batch_duration_ms', () => recordConsumedBatchDuration(250, 't', 'g')],
        [
            'recordConsumedBatchBackpressure',
            'consumed_batch_backpressure_duration_ms',
            () => recordConsumedBatchBackpressure(250, 't', 'g'),
        ],
    ] as const)('%s emits %s with prom label parity', async (_name, metricName, record) => {
        record()

        await reader.forceFlush()

        const points = dataPointsFor(metricName)
        expect(points).toHaveLength(1)
        expect(points[0].attributes).toEqual({ topic: 't', groupId: 'g' })
        expect(points[0].value.count).toEqual(1)
        expect(points[0].value.sum).toEqual(250)
    })

    it.each([
        ['recordBatchConsumed', () => recordBatchConsumed('t', 'g', [{ timestamp: 1 }], 2)],
        ['recordConsumedBatchDuration', () => recordConsumedBatchDuration(1, 't', 'g')],
        ['recordConsumedBatchBackpressure', () => recordConsumedBatchBackpressure(1, 't', 'g')],
    ] as const)('%s swallows a throwing OTel SDK so the consumer loop never dies on telemetry', (_name, record) => {
        const throwing = () => {
            throw new Error('otel exploded')
        }
        metricsApi.disable() // the API ignores a second setGlobalMeterProvider without this
        metricsApi.setGlobalMeterProvider({
            getMeter: () =>
                ({
                    createCounter: () => ({ add: throwing }),
                    createHistogram: () => ({ record: throwing }),
                }) as any,
        } as any)
        resetConsumerOtelInstrumentsForTests()

        expect(record).not.toThrow()
    })
})

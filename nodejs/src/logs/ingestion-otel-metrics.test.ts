import { metrics as metricsApi } from '@opentelemetry/api'
import {
    type DataPoint,
    type Histogram as HistogramDataPointValue,
    InMemoryMetricExporter,
    MeterProvider,
    PeriodicExportingMetricReader,
} from '@opentelemetry/sdk-metrics'

import {
    recordLogMessageDlq,
    recordLogMessageDropped,
    recordLogProcessingDuration,
    recordLogsAllowed,
    recordLogsDropped,
    recordLogsReceived,
    resetLogsIngestionInstrumentsForTests,
} from './ingestion-otel-metrics'

describe('ingestion-otel-metrics', () => {
    let exporter: InMemoryMetricExporter
    let provider: MeterProvider
    let reader: PeriodicExportingMetricReader

    beforeEach(() => {
        // Simulate the real startup-order hazard: a record call may run before a
        // provider exists (bound to the noop meter), with the provider registered
        // afterwards. Lazily acquired instruments must still deliver data recorded
        // after registration.
        resetLogsIngestionInstrumentsForTests()
        recordLogsReceived(1, 1)

        exporter = new InMemoryMetricExporter(0)
        reader = new PeriodicExportingMetricReader({ exporter, exportIntervalMillis: 60_000 })
        provider = new MeterProvider({ readers: [reader] })
        metricsApi.setGlobalMeterProvider(provider)
        resetLogsIngestionInstrumentsForTests()
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
        [
            'recordLogsReceived bytes',
            'logs_ingestion_bytes_received_total',
            () => recordLogsReceived(3072, 15),
            {},
            3072,
        ],
        [
            'recordLogsReceived records',
            'logs_ingestion_records_received_total',
            () => recordLogsReceived(3072, 15),
            {},
            15,
        ],
        ['recordLogsAllowed bytes', 'logs_ingestion_bytes_allowed_total', () => recordLogsAllowed(1024, 5), {}, 1024],
        ['recordLogsAllowed records', 'logs_ingestion_records_allowed_total', () => recordLogsAllowed(1024, 5), {}, 5],
        [
            'recordLogsDropped bytes',
            'logs_ingestion_bytes_dropped_total',
            () => recordLogsDropped(42, 2048, 10),
            { team_id: '42' },
            2048,
        ],
        [
            'recordLogsDropped records',
            'logs_ingestion_records_dropped_total',
            () => recordLogsDropped(42, 2048, 10),
            { team_id: '42' },
            10,
        ],
        [
            'recordLogMessageDropped',
            'logs_ingestion_message_dropped_count',
            () => recordLogMessageDropped('rate_limited', '42', 3),
            { reason: 'rate_limited', team_id: '42' },
            3,
        ],
        [
            'recordLogMessageDlq',
            'logs_ingestion_message_dlq_count',
            () => recordLogMessageDlq('KafkaError', '42'),
            { reason: 'KafkaError', team_id: '42' },
            1,
        ],
    ] as const)('%s emits %s', async (_name, metricName, record, attributes, value) => {
        record()

        await reader.forceFlush()

        const points = dataPointsFor<number>(metricName)
        expect(points).toHaveLength(1)
        expect(points[0].attributes).toEqual(attributes)
        expect(points[0].value).toEqual(value)
    })

    it('skips zero and negative amounts so no empty per-team series are created', async () => {
        recordLogsDropped(42, 0, 0)
        recordLogsReceived(0, -1)
        recordLogMessageDropped('rate_limited', '42', 0)

        await reader.forceFlush()

        const names = [
            'logs_ingestion_bytes_dropped_total',
            'logs_ingestion_records_dropped_total',
            'logs_ingestion_bytes_received_total',
            'logs_ingestion_records_received_total',
            'logs_ingestion_message_dropped_count',
        ]
        expect(names.map((name) => dataPointsFor(name).length)).toEqual([0, 0, 0, 0, 0])
    })

    it('records processing duration with the prom bucket ladder and pipeline attributes', async () => {
        const attributes = { json_parse_enabled: 'true', pii_scrub_enabled: 'false', compression_codec: 'snappy' }
        recordLogProcessingDuration(0.02, attributes)

        await reader.forceFlush()

        const points = dataPointsFor<HistogramDataPointValue>('logs_ingestion_processing_duration_seconds')
        expect(points).toHaveLength(1)
        expect(points[0].attributes).toEqual(attributes)
        expect(points[0].value.count).toEqual(1)
        expect(points[0].value.sum).toBeCloseTo(0.02)
        // Bucket parity with the prom histogram — dashboards translate 1:1 between the two sinks.
        expect(points[0].value.buckets.boundaries).toEqual([0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1])
    })
})

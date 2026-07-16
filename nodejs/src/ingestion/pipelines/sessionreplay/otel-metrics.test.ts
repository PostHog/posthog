import { metrics as metricsApi } from '@opentelemetry/api'
import {
    type DataPoint,
    type Histogram as HistogramDataPointValue,
    InMemoryMetricExporter,
    MeterProvider,
    PeriodicExportingMetricReader,
} from '@opentelemetry/sdk-metrics'

import {
    E2E_LAG_BOUNDARIES,
    recordE2eLag,
    recordEventsRateLimited,
    recordMessagesDroppedByRestrictions,
    recordNewSessionsRateLimited,
    recordS3UploadError,
    recordS3UploadLatency,
    recordSessionsFlushed,
    resetReplayIngestionInstrumentsForTests,
} from './otel-metrics'

describe('sessionreplay otel-metrics', () => {
    let exporter: InMemoryMetricExporter
    let provider: MeterProvider
    let reader: PeriodicExportingMetricReader

    beforeEach(() => {
        // Simulate the real startup-order hazard: a record call may run before a
        // provider exists (bound to the noop meter), with the provider registered
        // afterwards. Lazily acquired instruments must still deliver data recorded
        // after registration.
        resetReplayIngestionInstrumentsForTests()
        recordSessionsFlushed(1)

        exporter = new InMemoryMetricExporter(0)
        reader = new PeriodicExportingMetricReader({ exporter, exportIntervalMillis: 60_000 })
        provider = new MeterProvider({ readers: [reader] })
        metricsApi.setGlobalMeterProvider(provider)
        resetReplayIngestionInstrumentsForTests()
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
            'recordSessionsFlushed',
            'recording_blob_ingestion_v2_sessions_flushed_total',
            () => recordSessionsFlushed(7),
            {},
            7,
        ],
        [
            'recordEventsRateLimited',
            'recording_blob_ingestion_v2_events_rate_limited_total',
            () => recordEventsRateLimited(3),
            {},
            3,
        ],
        [
            'recordMessagesDroppedByRestrictions',
            'recording_blob_ingestion_v2_messages_dropped_by_restrictions',
            () => recordMessagesDroppedByRestrictions(2),
            {},
            2,
        ],
        [
            'recordNewSessionsRateLimited',
            'recording_blob_ingestion_v2_new_sessions_rate_limited_total',
            () => recordNewSessionsRateLimited(42, 5),
            { team_id: '42' },
            5,
        ],
        [
            'recordS3UploadError',
            'recording_blob_ingestion_v2_s3_upload_errors_total',
            () => recordS3UploadError(),
            {},
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

    it('skips zero and negative counts so no empty series are created', async () => {
        recordSessionsFlushed(0)
        recordEventsRateLimited(-1)

        await reader.forceFlush()

        expect(dataPointsFor('recording_blob_ingestion_v2_sessions_flushed_total')).toHaveLength(0)
        expect(dataPointsFor('recording_blob_ingestion_v2_events_rate_limited_total')).toHaveLength(0)
    })

    it('records e2e lag with the prom bucket ladder', async () => {
        recordE2eLag(42.5)

        await reader.forceFlush()

        const points = dataPointsFor<HistogramDataPointValue>('recording_blob_ingestion_v2_e2e_lag_seconds')
        expect(points).toHaveLength(1)
        expect(points[0].value.count).toEqual(1)
        expect(points[0].value.sum).toBeCloseTo(42.5)
        // Bucket parity with the prom histogram, so dashboards translate 1:1 between the two sinks.
        expect(points[0].value.buckets.boundaries).toEqual(E2E_LAG_BOUNDARIES)
    })

    it.each([
        ['recordSessionsFlushed', () => recordSessionsFlushed(1)],
        ['recordS3UploadLatency', () => recordS3UploadLatency(0.5)],
        ['recordE2eLag', () => recordE2eLag(1)],
    ] as const)('%s swallows a throwing OTel SDK so callers keep the original error', (_name, record) => {
        // These run in the ingestion hot path and in error handlers; a throw here
        // would mask the real processing error.
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
        resetReplayIngestionInstrumentsForTests()

        expect(record).not.toThrow()
    })
})

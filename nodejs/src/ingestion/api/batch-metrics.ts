import { Counter, Gauge, Histogram } from 'prom-client'

/**
 * Batch accounting for the ingest stream. The processor autoscaler reads
 * these series, so a path that skips them makes its pods look idle to KEDA
 * however much work they hold.
 */

const batchesProcessed = new Counter({
    name: 'ingestion_api_batches_processed_total',
    help: 'Total number of batches processed by the ingestion API',
})

const batchProcessingDuration = new Histogram({
    name: 'ingestion_api_batch_processing_duration_ms',
    help: 'Duration of batch processing in milliseconds',
    buckets: [10, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
})

const messagesProcessed = new Counter({
    name: 'ingestion_api_messages_processed_total',
    help: 'Total number of messages processed by the ingestion API',
})

const batchErrors = new Counter({
    name: 'ingestion_api_batch_errors_total',
    help: 'Total number of batch processing errors',
})

const batchesInFlight = new Gauge({
    name: 'ingestion_api_batches_in_flight',
    help: 'Number of accepted batches currently being processed by the ingestion API (concurrent batches)',
})

// Companion to `batchesInFlight`, and the one to autoscale on: batch sizes vary
// several-fold with consumer batching and routing, so a batch count says little
// about how much work a pod is holding. Events in flight is invariant to how the
// consumer slices a batch, which keeps a scaling target stable across dispatcher
// tuning changes.
const eventsInFlight = new Gauge({
    name: 'ingestion_api_events_in_flight',
    help: 'Number of events in accepted batches currently being processed by the ingestion API',
})

// The integral of `eventsInFlight` over time, accumulated one batch at a time:
// a batch holding N events for T seconds contributes N*T. Because
// integral(in_flight dt) equals sum(events * time in flight), rate() over this
// counter is the exact time-weighted mean events in flight for the interval,
// where the gauge above only reports whatever instant the scrape happened to
// land on. In-flight turns over on a sub-second timescale and scrapes are tens
// of seconds apart, so the gauge is far too noisy to autoscale on directly.
// Same relationship as container_cpu_usage_seconds_total and CPU utilization.
const eventSecondsInFlight = new Counter({
    name: 'ingestion_api_event_seconds_in_flight_total',
    help: 'Cumulative event-seconds spent in flight; rate() gives mean events in flight',
})

/** A batch the pipeline accepted, held until `batchReleased` credits its time in flight. */
export interface AcceptedBatch {
    events: number
    acceptedAt: number
}

/** The pipeline accepted the batch: it occupies a concurrent slot from now on. */
export function batchAccepted(events: number): AcceptedBatch {
    batchesInFlight.inc()
    eventsInFlight.inc(events)
    return { events, acceptedAt: Date.now() }
}

/** The batch's side effects are durably done and it was acked to the consumer. */
export function batchProcessed(batch: AcceptedBatch): void {
    batchesProcessed.inc()
    messagesProcessed.inc(batch.events)
    batchProcessingDuration.observe(Date.now() - batch.acceptedAt)
}

export function batchFailed(): void {
    batchErrors.inc()
}

/** The batch left the pipeline, acked or failed: free its slot and credit its event-seconds. */
export function batchReleased(batch: AcceptedBatch): void {
    batchesInFlight.dec()
    eventsInFlight.dec(batch.events)
    eventSecondsInFlight.inc((batch.events * (Date.now() - batch.acceptedAt)) / 1000)
}

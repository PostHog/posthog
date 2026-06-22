import { ingestionLagGauge, ingestionLagHistogram } from '~/common/metrics'
import { IngestedEventInfo } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

export interface RecordIngestionLagInput {
    ingested: Promise<IngestedEventInfo | null>[]
}

/**
 * Records ingestion lag for each ingested event, computed from the capture
 * time (`now` header) once the emission has been acked by Kafka. No sample
 * is recorded for events that were not ingested (failed emission, null info)
 * or that have no capture time.
 *
 * The step does not await the promises — it observes them and passes the
 * input through unchanged, so it can be placed anywhere downstream of the
 * emitting step.
 *
 * Pipeline and lane identity come from the registry-wide default labels
 * (`ingestion_pipeline`, `ingestion_lane`), so the metrics only carry
 * topic/partition labels.
 */
export function createRecordIngestionLagStep<T extends RecordIngestionLagInput>(): ProcessingStep<T, T> {
    return function recordIngestionLagStep(input: T): Promise<PipelineResult<T>> {
        for (const promise of input.ingested) {
            void promise.then(recordIngestionLag, () => {
                // The emission failed — the event was not ingested, so no lag sample
            })
        }
        return Promise.resolve(ok(input))
    }
}

function recordIngestionLag(info: IngestedEventInfo | null): void {
    if (info === null || info.capturedAt === undefined) {
        return
    }

    const lag = Date.now() - info.capturedAt.getTime()
    const partition = String(info.partition)
    ingestionLagGauge.labels({ topic: info.topic, partition }).set(lag)
    ingestionLagHistogram.labels({ partition }).observe(lag)
}

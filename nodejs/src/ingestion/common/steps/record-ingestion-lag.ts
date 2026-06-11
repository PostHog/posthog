import { Message, MessageHeader } from 'node-rdkafka'

import { ingestionLagGauge, ingestionLagHistogram } from '../../../common/metrics'
import { PipelineResultWithContext } from '../../pipelines/pipeline.interface'
import { PipelineResult, isOkResult, ok } from '../../pipelines/results'
import { ProcessingStep } from '../../pipelines/steps'

export interface RecordIngestionLagInput {
    elements: PipelineResultWithContext<
        unknown,
        { message: Pick<Message, 'topic' | 'partition' | 'headers'> },
        string
    >[]
}

/**
 * AfterBatch processing step that records ingestion lag for every OK result
 * in the batch, computed from the `now` Kafka header set by capture.
 *
 * Pipeline and lane identity come from the registry-wide default labels
 * (`ingestion_pipeline`, `ingestion_lane`), so the metrics only carry
 * topic/partition labels.
 */
export function createRecordIngestionLagStep<T extends RecordIngestionLagInput>(): ProcessingStep<T, T> {
    return function recordIngestionLagStep(input: T): Promise<PipelineResult<T>> {
        const nowMs = Date.now()

        for (const element of input.elements) {
            if (!isOkResult(element.result)) {
                continue
            }

            const { message } = element.context
            const capturedAt = parseNowHeader(message.headers)
            if (capturedAt === undefined) {
                continue
            }

            const lag = nowMs - capturedAt.getTime()
            const partition = String(message.partition)
            ingestionLagGauge.labels({ topic: message.topic, partition }).set(lag)
            ingestionLagHistogram.labels({ partition }).observe(lag)
        }

        return Promise.resolve(ok(input))
    }
}

function parseNowHeader(headers: MessageHeader[] | undefined): Date | undefined {
    for (const header of headers ?? []) {
        const value = header['now']
        if (value !== undefined) {
            const parsed = new Date(value.toString())
            if (!isNaN(parsed.getTime())) {
                return parsed
            }
        }
    }
    return undefined
}

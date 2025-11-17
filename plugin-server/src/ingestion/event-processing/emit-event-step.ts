import { KafkaProducerWrapper } from '../../kafka/producer'
import { RawKafkaEvent } from '../../types'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { eventProcessedAndIngestedCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface EmitEventStepConfig {
    kafkaProducer: KafkaProducerWrapper
    clickhouseJsonEventsTopic: string
}

export function createEmitEventStep<T extends { eventToEmit?: RawKafkaEvent }>(
    config: EmitEventStepConfig
): ProcessingStep<T, void> {
    return function emitEventStep(input: T): Promise<PipelineResult<void>> {
        const { eventToEmit } = input

        if (!eventToEmit) {
            return Promise.resolve(ok(undefined, []))
        }
        const { kafkaProducer, clickhouseJsonEventsTopic } = config

        // TODO: It's not great that we put the produce outcome in side effects, we should probably await it here
        //       but it might slow the pipeline down. Historically, it has always been like that.
        //       We should investigate this later.
        const emitPromise = kafkaProducer
            .produce({
                topic: clickhouseJsonEventsTopic,
                key: eventToEmit.uuid,
                value: Buffer.from(JSON.stringify(eventToEmit)),
                headers: { productTrack: productTrackHeader(eventToEmit) },
            })
            .then((result) => {
                // Increment the metric when event is successfully emitted
                eventProcessedAndIngestedCounter.inc()
                return result
            })
            .catch(async (error) => {
                // TODO: For now we have to live with the ingestion warning happening here
                //       Once the batch pipelines support warnings, we'll put it in the result
                // Some messages end up significantly larger than the original
                // after plugin processing, person & group enrichment, etc.
                if (error instanceof MessageSizeTooLarge) {
                    await captureIngestionWarning(kafkaProducer, eventToEmit.team_id, 'message_size_too_large', {
                        eventUuid: eventToEmit.uuid,
                        distinctId: eventToEmit.distinct_id,
                    })
                } else {
                    throw error
                }
            })

        return Promise.resolve(ok(undefined, [emitPromise]))
    }
}

export function productTrackHeader(event: RawKafkaEvent): string {
    return event.event.startsWith('$ai_') ? 'llma' : 'general'
}

import { PipelineEvent, RawKafkaEvent } from '../../types'
import { PipelineResult, dlq, drop } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface HandleClientIngestionWarningStepInput {
    event: PipelineEvent
}

export interface HandleClientIngestionWarningStepResult {
    eventToEmit?: RawKafkaEvent
}

export function createHandleClientIngestionWarningStep<
    TInput extends HandleClientIngestionWarningStepInput,
>(): ProcessingStep<TInput, HandleClientIngestionWarningStepResult> {
    return async function handleClientIngestionWarningStep(
        input: TInput
    ): Promise<PipelineResult<HandleClientIngestionWarningStepResult>> {
        const event = input.event

        if (event.event !== '$$client_ingestion_warning') {
            return Promise.resolve(
                dlq('unexpected_event_type', new Error(`Expected $$client_ingestion_warning, got ${event.event}`))
            )
        }

        return drop(
            'client_ingestion_warning',
            [],
            [
                {
                    type: 'client_ingestion_warning',
                    details: {
                        eventUuid: event.uuid,
                        event: event.event,
                        distinctId: event.distinct_id,
                        message: event.properties?.$$client_ingestion_warning_message,
                    },
                    alwaysSend: true,
                },
            ]
        )
    }
}

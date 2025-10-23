import { PipelineEvent } from '../../types'
import { PipelineResult, dlq, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface HandleClientIngestionWarningStepInput {
    event: PipelineEvent
}

export function createHandleClientIngestionWarningStep<
    TInput extends HandleClientIngestionWarningStepInput,
>(): ProcessingStep<TInput, void> {
    return async function handleClientIngestionWarningStep(input: TInput): Promise<PipelineResult<void>> {
        const event = input.event

        if (event.event !== '$$client_ingestion_warning') {
            return Promise.resolve(
                dlq('unexpected_event_type', new Error(`Expected $$client_ingestion_warning, got ${event.event}`))
            )
        }

        return ok(
            undefined,
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

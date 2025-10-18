import { EventPipelineResult } from '~/worker/ingestion/event-pipeline/runner'

import { PipelineEvent } from '../../types'
import { PipelineResult, dlq, drop } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createHandleClientIngestionWarningStep<TInput extends { event: PipelineEvent }>(): ProcessingStep<
    TInput,
    EventPipelineResult
> {
    return async function handleClientIngestionWarningStep(
        input: TInput
    ): Promise<PipelineResult<EventPipelineResult>> {
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

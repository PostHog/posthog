import { PipelineResult, drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { EventPipelineRunnerInput } from './event-pipeline-runner-v1-step'

export function createHandleClientIngestionWarningStep(): ProcessingStep<
    EventPipelineRunnerInput,
    EventPipelineRunnerInput
> {
    return async function handleClientIngestionWarningStep(
        input: EventPipelineRunnerInput
    ): Promise<PipelineResult<EventPipelineRunnerInput>> {
        const event = input.event

        if (event.event === '$$client_ingestion_warning') {
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

        return Promise.resolve(ok(input))
    }
}

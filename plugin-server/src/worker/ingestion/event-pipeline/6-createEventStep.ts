import { IngestionEvent } from '../../../types'
import { EventPipelineRunner, StepResult } from './runner'

export async function createEventStep(runner: EventPipelineRunner, event: IngestionEvent): Promise<StepResult> {
    const ingestionEvent = await runner.hub.eventsProcessor.createEvent(event)
    return runner.nextStep('runAsyncHandlersStep', ingestionEvent)
}

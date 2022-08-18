import { PreIngestionEvent } from '../../../types'
import { LazyPersonContainer } from '../lazy-person-container'
import { EventPipelineRunner, StepResult } from './runner'

export async function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    personContainer: LazyPersonContainer
): Promise<StepResult> {
    const ingestionEvent = await runner.hub.eventsProcessor.createEvent(event, personContainer)
    const person = await personContainer.get()
    return runner.nextStep('runAsyncHandlersStep', ingestionEvent, person)
}

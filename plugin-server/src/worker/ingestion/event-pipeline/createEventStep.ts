import { Person, PreIngestionEvent } from '../../../types'
import { EventPipelineRunner, StepResult } from './runner'

export async function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    person: Person | undefined
): Promise<StepResult> {
    await runner.hub.eventsProcessor.createEvent(event)
    return runner.nextStep('runAsyncHandlersStep', event, person)
}

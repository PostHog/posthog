import { PreIngestionEvent } from '../../../types'
import { status } from '../../../utils/status'
import { LazyPersonContainer } from '../lazy-person-container'
import { EventPipelineRunner, StepResult } from './runner'

export async function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    personContainer: LazyPersonContainer
): Promise<StepResult> {
    status.debug('🔁', 'Running createEventStep', { event: event.event, distinct_id: event.distinctId })
    const ingestionEvent = await runner.hub.eventsProcessor.createEvent(event, personContainer)
    return runner.nextStep('runAsyncHandlersStep', ingestionEvent, personContainer)
}

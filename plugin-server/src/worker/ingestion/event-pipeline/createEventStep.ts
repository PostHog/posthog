import { PreIngestionEvent } from '../../../types'
import { LazyPersonContainer } from '../lazy-person-container'
import { EventPipelineRunner } from './runner'

export async function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    personContainer: LazyPersonContainer
): Promise<PreIngestionEvent> {
    return await runner.hub.eventsProcessor.createEvent(event, personContainer)
}

import { PreIngestionEvent } from '../../../types'
import { LazyPersonContainer } from '../lazy-person-container'
import { EventPipelineRunner } from './runner'

export async function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    personContainer: LazyPersonContainer
): Promise<null> {
    await runner.hub.eventsProcessor.createEvent(event, personContainer)
    return null
}

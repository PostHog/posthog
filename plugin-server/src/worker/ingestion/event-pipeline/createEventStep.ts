import { Person, PreIngestionEvent, RawClickHouseEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export async function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    person: Person
): Promise<[RawClickHouseEvent, Promise<void>]> {
    return await runner.hub.eventsProcessor.createEvent(event, person)
}

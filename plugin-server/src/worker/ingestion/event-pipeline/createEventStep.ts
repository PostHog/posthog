import { Person, PreIngestionEvent, RawClickHouseEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export async function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    person: Person,
    processPerson: boolean
): Promise<[RawClickHouseEvent, Promise<void>]> {
    return await runner.eventsProcessor.createEvent(event, person, processPerson)
}

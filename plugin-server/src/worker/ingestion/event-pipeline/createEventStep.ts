import { Person, PreIngestionEvent, RawClickHouseEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    person: Person,
    processPerson: boolean
): [RawClickHouseEvent, Promise<void>] {
    return runner.eventsProcessor.createEvent(event, person, processPerson)
}

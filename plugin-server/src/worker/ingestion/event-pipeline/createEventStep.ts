import { Person, PreIngestionEvent, RawKafkaEvent } from '../../../types'
import { createEvent } from '../create-event'

export async function createEventStep(
    event: PreIngestionEvent,
    person: Person,
    processPerson: boolean
): Promise<RawKafkaEvent> {
    return Promise.resolve(createEvent(event, person, processPerson))
}

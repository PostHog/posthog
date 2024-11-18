import { Person, PreIngestionEvent, RawKafkaEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    person: Person,
    processPerson: boolean
): Promise<[RawKafkaEvent]> {
    console.log('about to create event')
    const res = runner.eventsProcessor.createEvent(event, person, processPerson)
    console.log('Result: ', res)
    return Promise.resolve([res])
}

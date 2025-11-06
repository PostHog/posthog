import { JwtVerificationStatus, Person, PreIngestionEvent, RawKafkaEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export async function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    person: Person,
    processPerson: boolean,
    verified: JwtVerificationStatus
): Promise<RawKafkaEvent> {
    return Promise.resolve(runner.eventsProcessor.createEvent(event, person, processPerson, verified))
}

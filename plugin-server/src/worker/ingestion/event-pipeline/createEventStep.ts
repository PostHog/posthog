import { Person, PreIngestionEvent, RawKafkaEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export async function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    person: Person,
    processPerson: boolean
): Promise<RawKafkaEvent> {
    const historicalMigration = runner.headers?.historical_migration ?? false
    const capturedAt = runner.headers?.now
    return Promise.resolve(
        runner.eventsProcessor.createEvent(event, person, processPerson, historicalMigration, capturedAt)
    )
}

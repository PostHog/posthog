import { Person, PreIngestionEvent, RawKafkaEvent } from '../../../types'
import { EventPipelineRunner, StepResult } from './runner'

export function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    person: Person,
    processPerson: boolean
): Promise<StepResult<RawKafkaEvent>> {
    return Promise.resolve({
        result: runner.eventsProcessor.createEvent(event, person, processPerson),
    })
}

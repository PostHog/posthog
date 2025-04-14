import { KafkaConsumerBreadcrumb, Person, PreIngestionEvent, RawKafkaEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    person: Person,
    processPerson: boolean,
    kafkaConsumerBreadcrumbs: KafkaConsumerBreadcrumb[]
): RawKafkaEvent {
    return runner.eventsProcessor.createEvent(event, person, processPerson, kafkaConsumerBreadcrumbs)
}

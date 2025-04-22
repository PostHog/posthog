import { RawKafkaEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export function emitEventStep(runner: EventPipelineRunner, event: RawKafkaEvent): [Promise<void>] {
    return [runner.eventsProcessor.emitEvent(event, runner.breadcrumbs)]
}

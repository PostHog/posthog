import { RawKafkaEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export async function emitEventStep(runner: EventPipelineRunner, event: RawKafkaEvent): Promise<[Promise<void>]> {
    return Promise.resolve([runner.eventsProcessor.emitEvent(event)])
}

import { RawClickHouseEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export function emitEventStep(runner: EventPipelineRunner, event: RawClickHouseEvent): [Promise<void>] {
    return [runner.eventsProcessor.emitEvent(event)]
}

import { RawClickHouseEvent, Team } from '../../../types'
import { EventPipelineRunner } from './runner'

export function emitEventStep(runner: EventPipelineRunner, event: RawClickHouseEvent, team: Team): [Promise<void>] {
    return [runner.eventsProcessor.emitEvent(event, team)]
}

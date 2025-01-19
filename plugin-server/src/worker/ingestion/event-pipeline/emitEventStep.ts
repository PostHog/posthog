import { RawKafkaEvent } from '../../../types'
import { EventPipelineRunner, StepResult } from './runner'

export function emitEventStep(runner: EventPipelineRunner, event: RawKafkaEvent): Promise<StepResult<null>> {
    const emitEventPromise = runner.eventsProcessor.emitEvent(event)
    return Promise.resolve({
        result: null,
        kafkaAcks: [emitEventPromise],
    })
}

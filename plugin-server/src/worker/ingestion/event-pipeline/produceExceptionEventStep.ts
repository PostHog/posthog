import { RawClickHouseEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export function produceExceptionEventStep(
    runner: EventPipelineRunner,
    event: RawClickHouseEvent
): Promise<[Promise<void>]> {
    const ack = runner.hub.kafkaProducer
        .produce({
            topic: runner.hub.EXCEPTIONS_SYMBOLIFICATION_KAFKA_TOPIC,
            key: event.uuid,
            value: Buffer.from(JSON.stringify(event)),
            waitForAck: true,
        })
        .catch((_) => {
            // Skipping error handling for now as it's taken care of above
        })

    return Promise.resolve([ack])
}

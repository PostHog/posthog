import { RawKafkaEvent } from '../../../types'
import { status } from '../../../utils/status'
import { EventPipelineRunner } from './runner'

export function produceExceptionSymbolificationEventStep(
    runner: EventPipelineRunner,
    event: RawKafkaEvent
): Promise<[Promise<void>]> {
    const ack = runner.hub.kafkaProducer
        .produce({
            topic: runner.hub.EXCEPTIONS_SYMBOLIFICATION_KAFKA_TOPIC,
            key: String(event.team_id),
            value: Buffer.from(JSON.stringify(event)),
            waitForAck: true,
        })
        .catch((error) => {
            status.warn('⚠️', 'Failed to produce exception event for symbolification', {
                team_id: event.team_id,
                uuid: event.uuid,
                error,
            })
            throw error
        })

    return Promise.resolve([ack])
}

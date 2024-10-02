import { status } from 'utils/status'

import { RawClickHouseEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export function produceExceptionSymbolificationEventStep(
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

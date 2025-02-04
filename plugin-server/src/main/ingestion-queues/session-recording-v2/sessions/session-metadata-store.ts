import { randomUUID } from 'crypto'

import { KafkaProducerWrapper } from '../../../../kafka/producer'
import { status } from '../../../../utils/status'
import { SessionBlockMetadata } from './session-block-metadata'

const SESSION_REPLAY_EVENTS_TOPIC = 'session_replay_events_v2'

export class SessionMetadataStore {
    constructor(private producer: KafkaProducerWrapper) {
        status.debug('🔍', 'session_metadata_store_created')
    }

    public async storeSessionBlock(metadata: SessionBlockMetadata): Promise<void> {
        const event = {
            uuid: randomUUID(),
            session_id: metadata.sessionId,
            team_id: metadata.teamId,
            start_timestamp: metadata.startTimestamp,
            end_timestamp: metadata.endTimestamp,
            urls: ['https://app.posthog.com/events', 'https://app.posthog.com/insights'], // Fake URLs for now
        }
        const eventBuffer = Buffer.from(JSON.stringify(event))

        await this.producer.produce({
            topic: SESSION_REPLAY_EVENTS_TOPIC,
            key: Buffer.from(metadata.sessionId),
            value: eventBuffer,
        })

        status.debug('🔍', 'session_metadata_store_block_stored', event)
    }
}

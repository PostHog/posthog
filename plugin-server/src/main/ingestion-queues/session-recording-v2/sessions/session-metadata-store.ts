import { randomUUID } from 'crypto'

import { KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS_V2_TEST } from '../../../../config/kafka-topics'
import { KafkaProducerWrapper } from '../../../../kafka/producer'
import { status } from '../../../../utils/status'
import { SessionBlockMetadata } from './session-block-metadata'

export class SessionMetadataStore {
    constructor(private producer: KafkaProducerWrapper) {
        status.debug('🔍', 'session_metadata_store_created')
    }

    public async storeSessionBlocks(blocks: SessionBlockMetadata[]): Promise<void> {
        status.info('🔍', 'session_metadata_store_storing_blocks', { count: blocks.length })

        const events = blocks.map((metadata) => ({
            uuid: randomUUID(),
            session_id: metadata.sessionId,
            team_id: metadata.teamId,
            distinct_id: metadata.distinctId,
            start_timestamp: metadata.startTimestamp,
            end_timestamp: metadata.endTimestamp,
            block_url: metadata.blockUrl,
        }))

        await this.producer.queueMessages({
            topic: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS_V2_TEST,
            messages: events.map((event) => ({
                key: event.session_id,
                value: JSON.stringify(event),
            })),
        })

        status.info('🔍', 'session_metadata_store_blocks_stored', { count: events.length })
    }
}

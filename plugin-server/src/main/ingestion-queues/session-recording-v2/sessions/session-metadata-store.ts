import { randomUUID } from 'crypto'

import { KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS } from '../../../../config/kafka-topics'
import { KafkaProducerWrapper } from '../../../../kafka/producer'
import { TimestampFormat } from '../../../../types'
import { logger } from '../../../../utils/logger'
import { castTimestampOrNow } from '../../../../utils/utils'
import { SessionBlockMetadata } from './session-block-metadata'

export class SessionMetadataStore {
    constructor(private producer: KafkaProducerWrapper) {
        logger.debug('🔍', 'session_metadata_store_created')
    }

    public async storeSessionBlocks(blocks: SessionBlockMetadata[]): Promise<void> {
        logger.info('🔍', 'session_metadata_store_storing_blocks', { count: blocks.length })

        const events = blocks.map((metadata) => ({
            // Common fields, setting them from both V1 and V2 is ok
            uuid: randomUUID(),
            session_id: metadata.sessionId,
            team_id: metadata.teamId,
            distinct_id: metadata.distinctId,
            // We set the primary timestamps because they have to be non-null, it won't cause issues
            first_timestamp: castTimestampOrNow(metadata.startDateTime, TimestampFormat.ClickHouse),
            last_timestamp: castTimestampOrNow(metadata.endDateTime, TimestampFormat.ClickHouse),
            // Primary fields, will be set by V1 at this stage
            first_url: null,
            urls: [],
            click_count: 0,
            keypress_count: 0,
            mouse_activity_count: 0,
            active_milliseconds: 0,
            console_log_count: 0,
            console_warn_count: 0,
            console_error_count: 0,
            size: 0,
            message_count: 0,
            snapshot_source: null,
            snapshot_library: null,
            event_count: 0,
            // V2-specific fields
            batch_id: metadata.batchId,
            block_url: metadata.blockUrl,
            // Secondary fields for V2 switchover
            first_timestamp_secondary: castTimestampOrNow(metadata.startDateTime, TimestampFormat.ClickHouse),
            last_timestamp_secondary: castTimestampOrNow(metadata.endDateTime, TimestampFormat.ClickHouse),
            first_url_secondary: metadata.firstUrl,
            urls_secondary: metadata.urls || [],
            click_count_secondary: metadata.clickCount || 0,
            keypress_count_secondary: metadata.keypressCount || 0,
            mouse_activity_count_secondary: metadata.mouseActivityCount || 0,
            active_milliseconds_secondary: metadata.activeMilliseconds || 0,
            console_log_count_secondary: metadata.consoleLogCount || 0,
            console_warn_count_secondary: metadata.consoleWarnCount || 0,
            console_error_count_secondary: metadata.consoleErrorCount || 0,
            size_secondary: metadata.size || 0,
            message_count_secondary: metadata.messageCount || 0,
            event_count_secondary: metadata.eventCount || 0,
            snapshot_source_secondary: metadata.snapshotSource,
            snapshot_library_secondary: metadata.snapshotLibrary,
        }))

        await this.producer.queueMessages({
            topic: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
            messages: events.map((event) => ({
                key: event.session_id,
                value: JSON.stringify(event),
            })),
        })

        await this.producer.flush()

        logger.info('🔍', 'session_metadata_store_blocks_stored', { count: events.length })
    }
}

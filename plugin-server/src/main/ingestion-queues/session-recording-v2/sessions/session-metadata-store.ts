import { randomUUID } from 'crypto'

import {
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS_V2_TEST,
} from '../../../../config/kafka-topics'
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

        const eventsV2 = blocks.map((metadata) => ({
            uuid: randomUUID(),
            session_id: metadata.sessionId,
            team_id: metadata.teamId,
            distinct_id: metadata.distinctId,
            batch_id: metadata.batchId,
            first_timestamp: castTimestampOrNow(metadata.startDateTime, TimestampFormat.ClickHouse),
            last_timestamp: castTimestampOrNow(metadata.endDateTime, TimestampFormat.ClickHouse),
            block_url: metadata.blockUrl,
            first_url: metadata.firstUrl,
            urls: metadata.urls || [],
            click_count: metadata.clickCount || 0,
            keypress_count: metadata.keypressCount || 0,
            mouse_activity_count: metadata.mouseActivityCount || 0,
            active_milliseconds: metadata.activeMilliseconds || 0,
            console_log_count: metadata.consoleLogCount || 0,
            console_warn_count: metadata.consoleWarnCount || 0,
            console_error_count: metadata.consoleErrorCount || 0,
            size: metadata.size || 0,
            message_count: metadata.messageCount || 0,
            snapshot_source: metadata.snapshotSource,
            snapshot_library: metadata.snapshotLibrary,
            event_count: metadata.eventCount || 0,
        }))

        // We publish "empty" events for the old version to facilitate the transition.
        //
        // Transition plan:
        // 1. we publish v2 metadata only to session_replay_events_v2_test
        // 2. we publish empty events to session_replay_events, blobby v1 overwrites the metadata, so the data in the table is correct
        // 3. we start serving all sessions from session_replay_events_v2_test
        // 4. we stop blobby v1
        // 5. we still use session_replay_events for listing sessions, it has all sessions because we're publishing "empty" events for the old version
        // 6. we change the read queries to merge data from session_replay_events and session_replay_events_v2_test
        // 7. we stop publishing empty events to session_replay_events
        // 8. we stop publishing to session_replay_events_v2_test
        // 9. we backfill missing data from session_replay_events_v2_test to session_replay_events
        // 10. we stop reading from session_replay_events_v2_test
        // 11. we remove the session_replay_events_v2_test tables and topics
        const eventsV1 = blocks.map((metadata) => ({
            uuid: randomUUID(),
            session_id: metadata.sessionId,
            team_id: metadata.teamId,
            distinct_id: metadata.distinctId,
            batch_id: metadata.batchId,
            first_timestamp: castTimestampOrNow(metadata.startDateTime, TimestampFormat.ClickHouse),
            last_timestamp: castTimestampOrNow(metadata.endDateTime, TimestampFormat.ClickHouse),
            block_url: null,
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
        }))

        await this.producer.queueMessages({
            topic: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS_V2_TEST,
            messages: eventsV2.map((event) => ({
                key: event.session_id,
                value: JSON.stringify(event),
            })),
        })
        await this.producer.queueMessages({
            topic: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
            messages: eventsV1.map((event) => ({
                key: event.session_id,
                value: JSON.stringify(event),
            })),
        })

        await this.producer.flush()

        logger.info('🔍', 'session_metadata_store_blocks_stored', { count: eventsV2.length })
    }
}

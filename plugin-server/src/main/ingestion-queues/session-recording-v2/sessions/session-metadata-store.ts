import { randomUUID } from 'crypto'

import { KafkaProducerWrapper } from '../../../../kafka/producer'
import { TimestampFormat } from '../../../../types'
import { logger } from '../../../../utils/logger'
import { castTimestampOrNow } from '../../../../utils/utils'
import { SessionBlockMetadata } from './session-block-metadata'

export class SessionMetadataStore {
    constructor(
        private producer: KafkaProducerWrapper,
        private kafkaTopic: string
    ) {
        logger.debug('🔍', 'session_metadata_store_created')
    }

    public async storeSessionBlocks(blocks: SessionBlockMetadata[]): Promise<void> {
        logger.info('🔍', 'session_metadata_store_storing_blocks', { count: blocks.length })

        const events = blocks.map((metadata) => ({
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
            retention_period_days: metadata.retentionPeriodDays,
        }))

        await this.producer.queueMessages({
            topic: this.kafkaTopic,
            messages: events.map((event) => ({
                key: event.session_id,
                value: JSON.stringify(event),
            })),
        })

        await this.producer.flush()

        logger.info('🔍', 'session_metadata_store_blocks_stored', { count: events.length })
    }
}

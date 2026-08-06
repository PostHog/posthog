import { randomUUID } from 'crypto'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'
import { castTimestampOrNow } from '~/common/utils/utils'
import { REPLAY_EVENTS_OUTPUT, ReplayEventsOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'
import { TimestampFormat } from '~/types'

import { KafkaMetadataSink, MetadataRecord } from './kafka-metadata-sink'
import { SessionBlockMetadata } from './session-block-metadata'

export type { SessionMetadataSink } from './kafka-metadata-sink'

export class SessionMetadataStore extends KafkaMetadataSink<ReplayEventsOutput> {
    constructor(outputs: IngestionOutputs<ReplayEventsOutput>) {
        super(outputs, REPLAY_EVENTS_OUTPUT)
        logger.debug('🔍', 'session_metadata_store_created')
    }

    protected toRecords(blocks: SessionBlockMetadata[]): MetadataRecord[] {
        return blocks.map((metadata) => ({
            key: metadata.sessionId,
            value: {
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
                is_deleted: metadata.isDeleted ? 1 : 0,
            },
        }))
    }
}

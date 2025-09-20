import { DateTime } from 'luxon'

import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { KafkaProducerWrapper, TopicMessage } from '../../kafka/producer'
import { PipelineEvent, TeamId, TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { logger } from '../../utils/logger'
import { IngestionWarningLimiter } from '../../utils/token-bucket'
import { UUIDT, castTimestampOrNow, castTimestampToClickhouseFormat } from '../../utils/utils'
import { KAFKA_EVENTS_DEAD_LETTER_QUEUE, KAFKA_INGESTION_WARNINGS } from './../../config/kafka-topics'

function getClickhouseTimestampOrNull(isoTimestamp?: string): string | null {
    return isoTimestamp
        ? castTimestampToClickhouseFormat(DateTime.fromISO(isoTimestamp), TimestampFormat.ClickHouseSecondPrecision)
        : null
}

export function generateEventDeadLetterQueueMessage(
    event: PipelineEvent | PluginEvent | ProcessedPluginEvent,
    error: unknown,
    teamId: number,
    errorLocation = 'plugin_server_ingest_event'
): TopicMessage {
    let errorMessage = 'Event ingestion failed. '
    if (error instanceof Error) {
        errorMessage += `Error: ${error.message}`
    }
    const pluginEvent: PluginEvent = { now: event.timestamp, sent_at: event.timestamp, ...event } as any as PluginEvent
    const { now, sent_at, timestamp, ...usefulEvent } = pluginEvent
    const currentTimestamp = getClickhouseTimestampOrNull(new Date().toISOString())
    const eventNow = getClickhouseTimestampOrNull(now)

    const deadLetterQueueEvent = {
        ...usefulEvent,
        event: safeClickhouseString(usefulEvent.event),
        distinct_id: safeClickhouseString(usefulEvent.distinct_id),
        site_url: safeClickhouseString(usefulEvent.site_url || ''),
        ip: safeClickhouseString(usefulEvent.ip || ''),
        id: new UUIDT().toString(),
        event_uuid: event.uuid,
        properties: JSON.stringify(event.properties ?? {}),
        now: eventNow,
        error_timestamp: currentTimestamp,
        raw_payload: JSON.stringify(event),
        error_location: safeClickhouseString(errorLocation),
        error: safeClickhouseString(errorMessage),
        tags: ['plugin_server', 'ingest_event'],
        team_id: event.team_id || teamId,
    }

    return {
        topic: KAFKA_EVENTS_DEAD_LETTER_QUEUE,
        messages: [
            {
                value: JSON.stringify(deadLetterQueueEvent),
            },
        ],
    }
}

// These get displayed under Data Management > Ingestion Warnings
// These warnings get displayed to end users. Make sure these errors are actionable and useful for them and
// also update IngestionWarningsView.tsx to display useful context.
export async function captureIngestionWarning(
    kafkaProducer: KafkaProducerWrapper,
    teamId: TeamId,
    type: string,
    details: Record<string, any>,
    /**
     * captureIngestionWarning will debounce calls using team id and type as the key
     * you can provide additional config in debounce.key to add to that key
     * for example to debounce by specific user id you can use debounce: { key: user_id }
     *
     * if alwaysSend is true, the message will be sent regardless of the debounce key
     * you can use this when a message is rare enough or important enough that it should always be sent
     */
    debounce?: { key?: string; alwaysSend?: boolean }
) {
    const limiter_key = `${teamId}:${type}:${debounce?.key || ''}`
    if (!!debounce?.alwaysSend || IngestionWarningLimiter.consume(limiter_key, 1)) {
        // TODO: Either here or in follow up change this to an await as we do care.
        void kafkaProducer
            .queueMessages({
                topic: KAFKA_INGESTION_WARNINGS,
                messages: [
                    {
                        value: JSON.stringify({
                            team_id: teamId,
                            type: type,
                            source: 'plugin-server',
                            details: JSON.stringify(details),
                            timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
                        }),
                    },
                ],
            })
            .catch((error) => {
                logger.warn('⚠️', 'Failed to produce ingestion warning', {
                    error,
                    team_id: teamId,
                    type,
                    details,
                })
            })
    }
    return Promise.resolve()
}

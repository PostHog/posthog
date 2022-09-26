import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { JobQueueManager } from 'main/job-queues/job-queue-manager'

import { JobName, TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { castTimestampToClickhouseFormat, UUIDT } from '../../utils/utils'
import { KAFKA_EVENTS_DEAD_LETTER_QUEUE } from './../../config/kafka-topics'

function getClickhouseTimestampOrNull(isoTimestamp?: string): string | null {
    return isoTimestamp
        ? castTimestampToClickhouseFormat(DateTime.fromISO(isoTimestamp), TimestampFormat.ClickHouseSecondPrecision)
        : null
}

export function generateEventDeadLetterQueueMessage(
    event: PluginEvent | ProcessedPluginEvent,
    error: unknown,
    errorLocation = 'plugin_server_ingest_event'
): ProducerRecord {
    let errorMessage = 'ingestEvent failed. '
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
    }

    const message = {
        topic: KAFKA_EVENTS_DEAD_LETTER_QUEUE,
        messages: [
            {
                value: JSON.stringify(deadLetterQueueEvent),
            },
        ],
    }
    return message
}

export async function captureWarning(
    jobQueueManager: JobQueueManager,
    team_id: number,
    description: string,
    extraProperties: Record<string, any>,
    eventUuid: string | null = null
): Promise<void> {
    if (eventUuid) {
        extraProperties['event_uuid'] = eventUuid
    }
    extraProperties['description'] = description

    const event: PluginEvent = {
        event: '$warning',
        distinct_id: '$posthog_warnings',
        team_id: team_id,
        properties: extraProperties,
        ip: null,
        site_url: '',
        now: Date.now().toString(),
        uuid: new UUIDT().toString(),
    }
    const job = {
        eventPayload: event,
        timestamp: Date.now(),
    }
    await jobQueueManager.enqueue(JobName.BUFFER_JOB, job, {
        key: 'team_id',
        tag: team_id.toString(),
    })
}

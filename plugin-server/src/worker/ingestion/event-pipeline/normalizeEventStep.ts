import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { EventHeaders } from '../../../types'
import { normalizeEvent, normalizeProcessPerson } from '../../../utils/event'
import { logger } from '../../../utils/logger'
import { compareTimestamps } from '../timestamp-comparison'
import { parseEventTimestamp } from '../timestamps'

export function normalizeEventStep(
    event: PluginEvent,
    processPerson: boolean,
    headers?: EventHeaders,
    timestampLoggingSampleRate?: number
): Promise<[PluginEvent, DateTime]> {
    let timestamp: DateTime
    try {
        event = normalizeEvent(event)
        event = normalizeProcessPerson(event, processPerson)
        timestamp = parseEventTimestamp(event)

        // Compare timestamp from headers with event.timestamp - they should be equal if implemented correctly
        if (headers) {
            compareTimestamps(
                timestamp.toISO() || undefined,
                headers,
                event.team_id,
                event.uuid,
                'normalize_event_step',
                timestampLoggingSampleRate
            )
        }
    } catch (error) {
        logger.warn('⚠️', 'Failed normalizing event', {
            team_id: event.team_id,
            uuid: event.uuid,
            error,
        })
        throw error
    }

    // We need to be "async" to deal with how `runStep` currently works.
    return Promise.resolve([event, timestamp])
}

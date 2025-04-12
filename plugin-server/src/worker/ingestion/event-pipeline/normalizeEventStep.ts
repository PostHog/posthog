import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { normalizeEvent, normalizeProcessPerson } from '../../../utils/event'
import { logger } from '../../../utils/logger'
import { parseEventTimestamp } from '../timestamps'

export function normalizeEventStep(event: PluginEvent, processPerson: boolean): Promise<[PluginEvent, DateTime]> {
    let timestamp: DateTime
    try {
        event = normalizeEvent(event)
        event = normalizeProcessPerson(event, processPerson)
        timestamp = parseEventTimestamp(event)
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

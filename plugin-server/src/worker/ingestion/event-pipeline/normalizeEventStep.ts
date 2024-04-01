import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { normalizeEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { parseEventTimestamp } from '../timestamps'

export function normalizeEventStep(event: PluginEvent): [PluginEvent, DateTime] {
    let timestamp: DateTime
    try {
        event = normalizeEvent(event)
        timestamp = parseEventTimestamp(event)
    } catch (error) {
        status.warn('⚠️', 'Failed normalizing event', {
            team_id: event.team_id,
            uuid: event.uuid,
            error,
        })
        throw error
    }

    return [event, timestamp]
}

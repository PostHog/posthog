import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

export function processEvent(event: PluginEvent, _meta: LegacyTransformationPluginMeta) {
    if (!event['timestamp']) {
        return event
    }

    event.properties = event.properties ?? {}

    let dt: DateTime | null = null

    // Handle Unix timestamp (milliseconds)
    if (typeof event['timestamp'] === 'number') {
        dt =
            event['timestamp'] > 999999999999
                ? DateTime.fromMillis(event['timestamp'])
                : DateTime.fromSeconds(event['timestamp'])
    }
    // Handle ISO string
    else if (typeof event['timestamp'] === 'string') {
        dt = DateTime.fromISO(event['timestamp'])
    }

    if (dt && dt.isValid) {
        event.properties['day_of_the_week'] = dt.toFormat('EEEE')
        event.properties['day'] = dt.day
        event.properties['month'] = dt.month
        event.properties['year'] = dt.year
        event.properties['hour'] = dt.hour
        event.properties['minute'] = dt.minute
    }

    return event
}

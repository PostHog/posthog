import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

export function processEvent(event: PluginEvent, _meta: LegacyTransformationPluginMeta) {
    if (event.properties) {
        let timestamp = event.properties.$time ? new Date(event.properties.$time * 1000) : null

        if (!timestamp && event['timestamp']) {
            try {
                timestamp = new Date(event['timestamp'])
                // Check if the date is valid
                if (isNaN(timestamp.getTime())) {
                    timestamp = null
                }
            } catch {
                timestamp = null
            }
        }

        if (timestamp) {
            event.properties['day_of_the_week'] = timestamp.toLocaleDateString('en-GB', { weekday: 'long' })
            const date = timestamp.toLocaleDateString('en-GB').split('/')
            event.properties['day'] = date[0]
            event.properties['month'] = date[1]
            event.properties['year'] = date[2]
            event.properties['hour'] = timestamp.getHours()
            event.properties['minute'] = timestamp.getMinutes()
        }
    }

    return event
}

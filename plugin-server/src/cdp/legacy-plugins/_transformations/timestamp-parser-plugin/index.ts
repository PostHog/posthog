import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

export function processEvent(event: PluginEvent, _meta: LegacyTransformationPluginMeta) {
    if (event.properties && event['timestamp'] && !isNaN(event['timestamp'] as any)) {
        const eventDate = new Date(event['timestamp'])
        event.properties['day_of_the_week'] = eventDate.toLocaleDateString('en-GB', { weekday: 'long' })
        const date = eventDate.toLocaleDateString('en-GB').split('/')
        event.properties['day'] = Number(date[0])
        event.properties['month'] = Number(date[1])
        event.properties['year'] = Number(date[2])
        event.properties['hour'] = eventDate.getHours()
        event.properties['minute'] = eventDate.getMinutes()
    }

    return event
}

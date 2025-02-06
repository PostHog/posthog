import { PluginEvent, StorageExtension } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

export async function firstTimeEventTrackerPluginProcessEventAsync(
    event: PluginEvent,
    { config, global }: LegacyTransformationPluginMeta,
    storage: Pick<StorageExtension, 'get' | 'set'>
) {
    global.eventsToTrack = global.eventsToTrack || new Set(config.events.split(','))

    if (global.eventsToTrack.has(event.event)) {
        if (!event.properties) {
            event.properties = {}
        }
        const eventSeenBefore = await storage.get(event.event, false)
        const eventSeenBeforeForUser = await storage.get(`${event.event}_${event.distinct_id}`, false)
        event.properties['is_first_event_ever'] = !eventSeenBefore
        event.properties['is_first_event_for_user'] = !eventSeenBeforeForUser

        if (!eventSeenBeforeForUser) {
            await storage.set(`${event.event}_${event.distinct_id}`, true)
            if (!eventSeenBefore) {
                await storage.set(event.event, true)
            }
        }
    }

    return event
}

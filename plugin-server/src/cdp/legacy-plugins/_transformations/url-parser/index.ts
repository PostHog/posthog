import { URLSearchParams } from 'url'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

// Processes each event, optionally transforming it
export function processEvent(event: PluginEvent, { logger }: LegacyTransformationPluginMeta) {
    try {
        // Some events (such as $identify) don't have properties
        if (event.properties && event.properties.$current_url) {
            const url = new URL(event.properties.$current_url)
            const params = new URLSearchParams(url.searchParams)
            for (const [key, val] of params.entries()) {
                event.properties[`url_${key}`] = val
            }
        }
    } catch (e) {
        logger.error('Error parsing URL', e)
    }
    return event
}

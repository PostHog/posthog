// Learn more about plugins at: https://posthog.com/docs/plugins/build/overview

import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPlugin, LegacyTransformationPluginMeta } from '../../types'
import metadata from './plugin.json'

// Processes each event, optionally transforming it
export function processEvent(event: PluginEvent, { config }: LegacyTransformationPluginMeta) {
    // Some events (such as $identify) don't have properties
    if (event.properties && event.properties[config.property_key]) {
        if (!config.property_values || config.property_values == '') {
            return null
        }
        const values = config.property_values.split(',')
        if (values.indexOf(event.properties[config.property_key]) > -1) {
            return null
        }
    }
    // Return the event to be ingested, or return null to discard
    return event
}

export const dropEventsOnPropertyPlugin: LegacyTransformationPlugin = {
    id: 'drop-events-on-property-plugin',
    metadata,
    processEvent,
}

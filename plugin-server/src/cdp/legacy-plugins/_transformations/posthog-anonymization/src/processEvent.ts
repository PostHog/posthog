import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../../types'
import { encodePrivateField } from './encodePrivateField'
import { normalizePath } from './normalizePath'

export function processEvent(event: PluginEvent, { config }: LegacyTransformationPluginMeta): PluginEvent {
    if (!config.salt) {
        return event
    }
    if (!config.privateFields) {
        return event
    }

    if (event.properties && event.properties['$current_url']) {
        event.properties['$current_url'] = normalizePath(event.properties['$current_url'])
    }

    if (event.properties && event.properties['$set'] && event.properties['$set']['$current_url']) {
        event.properties['$set']['$current_url'] = normalizePath(event.properties['$set']['$current_url'])
    }

    if (event.properties && event.properties['$set_once'] && event.properties['$set_once']['$initial_current_url']) {
        event.properties['$set_once']['$initial_current_url'] = normalizePath(
            event.properties['$set_once']['$initial_current_url']
        )
    }

    config.privateFields.split(',').forEach((privateField: string) => {
        if (event.properties && privateField in event.properties) {
            event.properties[privateField] = encodePrivateField(event.properties[privateField] as string, config.salt)
        }

        if (privateField in event) {
            ;(event as any)[privateField] = encodePrivateField((event as any)[privateField] as string, config.salt)
        }
    })

    return event
}

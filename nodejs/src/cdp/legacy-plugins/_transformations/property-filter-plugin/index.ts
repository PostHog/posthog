import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

export function setupPlugin({ config, global }: LegacyTransformationPluginMeta) {
    global.propertiesToFilter = config.properties.split(',')
}

function recursiveRemoveFilterObject(properties: Record<string, any>, propertyToFilterParts: string[]) {
    // if we've reached the final filter part, then we can remove the key if it exists
    // otherwise recursively go down the properties object with the remaining filter parts
    const currentKey = propertyToFilterParts.shift()
    if (currentKey != undefined && currentKey in properties) {
        if (propertyToFilterParts.length == 0) {
            delete properties[currentKey]
        } else {
            recursiveRemoveFilterObject(properties[currentKey], propertyToFilterParts)
        }
    }
}

export function processEvent(event: PluginEvent, { global }: LegacyTransformationPluginMeta) {
    const propertiesCopy = event.properties ? { ...event.properties } : {}

    for (const propertyToFilter of global.propertiesToFilter) {
        if (propertyToFilter === '$ip') {
            event.ip = null
        }

        recursiveRemoveFilterObject(propertiesCopy, propertyToFilter.split('.'))
    }

    return { ...event, properties: propertiesCopy }
}

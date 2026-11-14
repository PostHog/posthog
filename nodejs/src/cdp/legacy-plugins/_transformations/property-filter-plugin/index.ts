import { PluginEvent } from '~/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

export function setupPlugin({ config, global }: LegacyTransformationPluginMeta) {
    global.propertiesToFilter = config.properties.split(',').map((property: string) => property.trim())
}

function recursiveRemoveFilterObject(properties: Record<string, any>, propertyToFilterParts: string[]) {
    if (properties === null || typeof properties !== 'object') {
        return
    }
    // if we've reached the final filter part, then we can remove the key if it exists
    // otherwise recursively go down the properties object with the remaining filter parts
    const currentKey = propertyToFilterParts.shift()
    // An own-property check, so that a path such as `__proto__.toString` cannot reach and delete a built-in.
    if (currentKey != undefined && Object.hasOwn(properties, currentKey)) {
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

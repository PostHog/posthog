import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { eventToPersonProperties, initialEventToPersonProperties } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'
import { personPropertyKeyUpdateCounter } from './metrics'

export interface PropertyUpdates {
    toSet: Properties
    toUnset: string[]
    hasChanges: boolean
}

// These events are processed in a separate pipeline, so we don't allow person property updates
// because there is no ordering guaranteed across them with other person updates
const NO_PERSON_UPDATE_EVENTS = new Set(['$exception', '$$heatmap'])
const PERSON_EVENTS = new Set(['$identify', '$create_alias', '$merge_dangerously', '$set'])

// For tracking what property keys cause us to update persons
// tracking all properties we add from the event, 'geoip' for '$geoip_*' or '$initial_geoip_*' and 'other' for anything outside of those
function getMetricKey(key: string): string {
    if (key.startsWith('$geoip_') || key.startsWith('$initial_geoip_')) {
        return 'geoIP'
    }
    if (eventToPersonProperties.has(key)) {
        return key
    }
    if (initialEventToPersonProperties.has(key)) {
        return key
    }
    return 'other'
}

/**
 * Computes property changes from an event without modifying personProperties
 * @param event The event to extract property changes from
 * @param personProperties Current person properties (not modified)
 * @returns Object with properties to set, unset, and whether there are changes
 */
export function computeEventPropertyUpdates(event: PluginEvent, personProperties: Properties): PropertyUpdates {
    if (NO_PERSON_UPDATE_EVENTS.has(event.event)) {
        return { hasChanges: false, toSet: {}, toUnset: [] }
    }

    const properties: Properties = event.properties!['$set'] || {}
    const propertiesOnce: Properties = event.properties!['$set_once'] || {}
    const unsetProps = event.properties!['$unset']
    const unsetProperties: Array<string> = Array.isArray(unsetProps) ? unsetProps : Object.keys(unsetProps || {}) || []

    let hasChanges = false
    const toSet: Properties = {}
    const toUnset: string[] = []

    Object.entries(propertiesOnce).forEach(([key, value]) => {
        if (typeof personProperties[key] === 'undefined') {
            hasChanges = true
            toSet[key] = value
        }
    })

    Object.entries(properties).forEach(([key, value]) => {
        if (personProperties[key] !== value) {
            if (typeof personProperties[key] === 'undefined' || shouldUpdatePersonIfOnlyChange(event, key)) {
                hasChanges = true
            }
            toSet[key] = value
        }
    })

    unsetProperties.forEach((propertyKey) => {
        if (propertyKey in personProperties) {
            if (typeof propertyKey === 'string') {
                hasChanges = true
                toUnset.push(propertyKey)
            }
        }
    })

    return { hasChanges, toSet, toUnset }
}

/**
 * @param propertyUpdates The computed property updates to apply
 * @param personProperties Properties of the person to be updated, these are updated in place.
 * @returns true if the properties were changed, false if they were not
 */
export function applyEventPropertyUpdates(propertyUpdates: PropertyUpdates, personProperties: Properties): boolean {
    let updated = false
    const metricsKeys = new Set<string>()

    // Apply properties to set
    Object.entries(propertyUpdates.toSet).forEach(([key, value]) => {
        if (personProperties[key] !== value) {
            updated = true
        }
        metricsKeys.add(getMetricKey(key))
        personProperties[key] = value
    })

    // Apply properties to unset
    propertyUpdates.toUnset.forEach((propertyKey) => {
        if (propertyKey in personProperties) {
            if (typeof propertyKey !== 'string') {
                logger.warn('🔔', 'unset_property_key_not_string', { propertyKey, toUnset: propertyUpdates.toUnset })
                return
            }
            updated = true
            metricsKeys.add(getMetricKey(propertyKey))
            delete personProperties[propertyKey]
        }
    })

    metricsKeys.forEach((key) => personPropertyKeyUpdateCounter.labels({ key: key }).inc())
    return updated
}

// Minimize useless person updates by not overriding properties if it's not a person event and we added from the event
// They will still show up for PoE as it's not removed from the event, we just don't update the person in PG anymore
function shouldUpdatePersonIfOnlyChange(event: PluginEvent, key: string): boolean {
    if (PERSON_EVENTS.has(event.event)) {
        // for person events always update everything
        return true
    }
    // These are properties we add from the event and some change often, it's useless to update person always
    if (eventToPersonProperties.has(key)) {
        return false
    }
    // same as above, coming from GeoIP plugin
    if (key.startsWith('$geoip_')) {
        return false
    }
    return true
}

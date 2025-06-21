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
 * @param personProperties Properties of the person to be updated, these are updated in place.
 * @returns true if the properties were changed, false if they were not
 */
export function applyEventPropertyUpdates(event: PluginEvent, personProperties: Properties): boolean {
    // this relies on making changes to the object instance, so...
    // if we should not update the person,
    // we return early before changing any values
    if (NO_PERSON_UPDATE_EVENTS.has(event.event)) {
        return false
    }

    const properties: Properties = event.properties!['$set'] || {}
    const propertiesOnce: Properties = event.properties!['$set_once'] || {}
    const unsetProps = event.properties!['$unset']
    const unsetProperties: Array<string> = Array.isArray(unsetProps) ? unsetProps : Object.keys(unsetProps || {}) || []

    let updated = false
    // tracking as set because we only care about if other or geoip was the cause of the update, not how many properties got updated
    const metricsKeys = new Set<string>()
    Object.entries(propertiesOnce).forEach(([key, value]) => {
        if (typeof personProperties[key] === 'undefined') {
            updated = true
            metricsKeys.add(getMetricKey(key))
            personProperties[key] = value
        }
    })

    Object.entries(properties).forEach(([key, value]) => {
        // note: due to the type of equality check here
        // if there is an array or object nested as a $set property
        // we'll always return true even if those objects/arrays contain the same values
        // This results in a shallow merge of the properties from event into the person properties
        if (personProperties[key] !== value) {
            if (typeof personProperties[key] === 'undefined' || shouldUpdatePersonIfOnlyChange(event, key)) {
                updated = true
            }
            metricsKeys.add(getMetricKey(key))
            personProperties[key] = value
        }
    })
    unsetProperties.forEach((propertyKey) => {
        if (propertyKey in personProperties) {
            if (typeof propertyKey !== 'string') {
                logger.warn('🔔', 'unset_property_key_not_string', { propertyKey, unsetProperties })
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

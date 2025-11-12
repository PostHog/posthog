import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { cloneObject } from '~/utils/utils'

import { InternalPerson } from '../../../types'
import { logger } from '../../../utils/logger'
import { personProfileIgnoredPropertiesCounter, personProfileUpdateOutcomeCounter } from './metrics'
import { eventToPersonProperties, initialEventToPersonProperties } from './person-property-utils'

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
export function getMetricKey(key: string): string {
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
        personProfileUpdateOutcomeCounter.labels({ outcome: 'unsupported' }).inc()
        return { hasChanges: false, toSet: {}, toUnset: [] }
    }

    const properties: Properties = event.properties!['$set'] || {}
    const propertiesOnce: Properties = event.properties!['$set_once'] || {}
    const unsetProps = event.properties!['$unset']
    const unsetProperties: Array<string> = Array.isArray(unsetProps) ? unsetProps : Object.keys(unsetProps || {}) || []

    let hasChanges = false
    let hasNonFilteredChanges = false
    const toSet: Properties = {}
    const toUnset: string[] = []
    const ignoredProperties: string[] = []

    Object.entries(propertiesOnce).forEach(([key, value]) => {
        if (typeof personProperties[key] === 'undefined') {
            hasChanges = true
            toSet[key] = value
            if (shouldUpdatePersonIfOnlyChange(event, key)) {
                hasNonFilteredChanges = true
            }
        }
    })

    Object.entries(properties).forEach(([key, value]) => {
        if (personProperties[key] !== value) {
            const isNewProperty = typeof personProperties[key] === 'undefined'
            const shouldUpdate = isNewProperty || shouldUpdatePersonIfOnlyChange(event, key)

            if (shouldUpdate) {
                hasChanges = true
                hasNonFilteredChanges = true
            } else {
                hasChanges = true
                ignoredProperties.push(key)
            }
            toSet[key] = value
        }
    })

    unsetProperties.forEach((propertyKey) => {
        if (propertyKey in personProperties) {
            if (typeof propertyKey === 'string') {
                hasChanges = true
                hasNonFilteredChanges = true
                toUnset.push(propertyKey)
            }
        }
    })

    // Track person profile update outcomes at event level
    const hasPropertyChanges = Object.keys(toSet).length > 0 || toUnset.length > 0
    if (hasPropertyChanges) {
        if (hasNonFilteredChanges) {
            personProfileUpdateOutcomeCounter.labels({ outcome: 'changed' }).inc()
        } else {
            personProfileUpdateOutcomeCounter.labels({ outcome: 'ignored' }).inc()
            ignoredProperties.forEach((property) => {
                personProfileIgnoredPropertiesCounter.labels({ property }).inc()
            })
        }
    } else {
        personProfileUpdateOutcomeCounter.labels({ outcome: 'no_change' }).inc()
    }

    return { hasChanges, toSet, toUnset }
}

/**
 * @param propertyUpdates The computed property updates to apply
 * @param person The person to apply updates to - a new person object is returned with updated properties
 * @returns [updatedPerson, wasUpdated] - new person object and boolean indicating if changes were made
 */
export function applyEventPropertyUpdates(
    propertyUpdates: PropertyUpdates,
    person: InternalPerson
): [InternalPerson, boolean] {
    let updated = false

    // Create a copy of the person with copied properties
    const updatedPerson = cloneObject(person)

    // Apply properties to set
    Object.entries(propertyUpdates.toSet).forEach(([key, value]) => {
        if (updatedPerson.properties[key] !== value) {
            updated = true
        }
        updatedPerson.properties[key] = value
    })

    // Apply properties to unset
    propertyUpdates.toUnset.forEach((propertyKey) => {
        if (propertyKey in updatedPerson.properties) {
            if (typeof propertyKey !== 'string') {
                logger.warn('🔔', 'unset_property_key_not_string', { propertyKey, toUnset: propertyUpdates.toUnset })
                return
            }
            updated = true
            delete updatedPerson.properties[propertyKey]
        }
    })

    return [updatedPerson, updated]
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

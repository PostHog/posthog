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
    shouldForceUpdate: boolean // True for PERSON_EVENTS ($identify, $set, etc.) to bypass batch-level filtering
}

// These events are processed in a separate pipeline, so we don't allow person property updates
// because there is no ordering guaranteed across them with other person updates
const NO_PERSON_UPDATE_EVENTS = new Set(['$exception', '$$heatmap'])
const PERSON_EVENTS = new Set(['$identify', '$create_alias', '$merge_dangerously', '$set'])

// GeoIP properties that should still trigger person updates even when other geoip properties are blocked
// These are commonly used for segmentation and are worth keeping up-to-date
const ALLOWED_GEOIP_PROPERTIES = new Set(['$geoip_country_name', '$geoip_city_name'])

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
 * @param updateAllProperties When true, all property changes trigger updates (no filtering)
 * @returns Object with properties to set, unset, and whether there are changes
 */
export function computeEventPropertyUpdates(
    event: PluginEvent,
    personProperties: Properties,
    updateAllProperties: boolean = false
): PropertyUpdates {
    if (NO_PERSON_UPDATE_EVENTS.has(event.event)) {
        personProfileUpdateOutcomeCounter.labels({ outcome: 'unsupported' }).inc()
        return { hasChanges: false, toSet: {}, toUnset: [], shouldForceUpdate: false }
    }

    // Check if this is a PERSON_EVENT that should bypass batch-level filtering
    // Also force update when updateAllProperties is enabled
    const shouldForceUpdate = PERSON_EVENTS.has(event.event) || updateAllProperties

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
            if (shouldUpdatePersonIfOnlyChange(event, key, updateAllProperties)) {
                hasNonFilteredChanges = true
            }
        }
    })

    // First pass: detect if any property would trigger an update
    // If so, all changed properties in this $set should be updated together
    let anyPropertyTriggersUpdate = false
    const changedProperties: Array<[string, unknown]> = []

    Object.entries(properties).forEach(([key, value]) => {
        if (personProperties[key] !== value) {
            changedProperties.push([key, value])
            const isNewProperty = typeof personProperties[key] === 'undefined'
            if (isNewProperty || shouldUpdatePersonIfOnlyChange(event, key, updateAllProperties)) {
                anyPropertyTriggersUpdate = true
            }
        }
    })

    // Second pass: apply changes - if any property triggers update, all do
    changedProperties.forEach(([key, value]) => {
        hasChanges = true
        if (anyPropertyTriggersUpdate) {
            hasNonFilteredChanges = true
        } else {
            ignoredProperties.push(key)
        }
        toSet[key] = value
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

    // Track person profile update outcomes at event level (skip when updateAllProperties is enabled)
    if (!updateAllProperties) {
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
    }

    return { hasChanges, toSet, toUnset, shouldForceUpdate }
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

/**
 * Determines if a property key should be filtered out from triggering person updates.
 * These are properties that change frequently but aren't valuable enough to update the person record for.
 *
 * This is the single source of truth for property filtering logic, used by both:
 * - Event-level processing (computeEventPropertyUpdates)
 * - Batch-level processing (getPersonUpdateOutcome in batch-writing-person-store)
 */
export function isFilteredPersonPropertyKey(key: string): boolean {
    // These are properties we add from the event and some change often, it's useless to update person always
    if (eventToPersonProperties.has(key)) {
        return true
    }
    // same as above, coming from GeoIP plugin
    // but allow country and city updates as they're commonly used for segmentation
    if (key.startsWith('$geoip_')) {
        return !ALLOWED_GEOIP_PROPERTIES.has(key)
    }
    return false
}

// Minimize useless person updates by not overriding properties if it's not a person event and we added from the event
// They will still show up for PoE as it's not removed from the event, we just don't update the person in PG anymore
function shouldUpdatePersonIfOnlyChange(event: PluginEvent, key: string, updateAllProperties: boolean): boolean {
    if (updateAllProperties) {
        // When flag is enabled, all property changes trigger updates
        return true
    }
    if (PERSON_EVENTS.has(event.event)) {
        // for person events always update everything
        return true
    }
    return !isFilteredPersonPropertyKey(key)
}

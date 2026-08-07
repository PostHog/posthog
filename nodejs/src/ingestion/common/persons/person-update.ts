import { personProfileIgnoredPropertiesCounter, personProfileUpdateOutcomeCounter } from '~/common/persons/metrics'
import {
    eventToPersonProperties,
    initialEventToPersonProperties,
    isFilteredPersonUpdateProperty,
} from '~/common/persons/person-property-utils'
import { logger } from '~/common/utils/logger'
import { cloneObject } from '~/common/utils/utils'
import { PluginEvent, Properties } from '~/plugin-scaffold'
import { InternalPerson } from '~/types'

export interface PropertyUpdates {
    toSet: Properties
    toUnset: string[]
    hasChanges: boolean
    shouldForceUpdate: boolean // True for PERSON_EVENTS ($identify, $set, etc.) to bypass batch-level filtering
}

/**
 * What one event asks of a person, extracted without consulting person
 * state: the ops as the event stated them. Interpretation of the event
 * (denylist, force semantics) happens here; what the ops mean *given
 * current state* is each store's concern — the Postgres store refines
 * them against its snapshot, the personhog store ships them for the
 * leader to resolve authoritatively.
 */
export interface EventOps {
    /** $set values, as stated on the event. */
    set: Properties
    /** $set_once values for keys not shadowed by a $set on the same event. */
    setOnce: Properties
    /** $unset keys. */
    unset: string[]
    /** The event kind never writes person properties ($exception, $$heatmap). */
    denied: boolean
    /** PERSON_EVENTS or updateAllProperties — bypasses batch-level filtering. */
    shouldForceUpdate: boolean
    /** The event asserts identity; OR-merged, never reverts. Set by the caller from event-kind context. */
    isIdentified?: boolean
    /** Hour-truncated last-seen candidate, epoch ms; max-merged. Set by the caller from its context. */
    lastSeenAtMs?: number
    /** The event name, for the leader's denylist and metrics attribution. */
    eventName: string
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
 * Extracts what an event asks of a person, without consulting person state.
 * A $set shadows a $set_once for the same key within the event (the set
 * would win at application anyway), and an event on the denylist yields
 * empty ops with `denied` set.
 */
export function extractEventOps(event: PluginEvent, updateAllProperties: boolean = false): EventOps {
    if (NO_PERSON_UPDATE_EVENTS.has(event.event)) {
        personProfileUpdateOutcomeCounter.labels({ outcome: 'unsupported' }).inc()
        return {
            set: {},
            setOnce: {},
            unset: [],
            denied: true,
            shouldForceUpdate: false,
            eventName: event.event,
        }
    }

    const set: Properties = { ...(event.properties!['$set'] || {}) }
    const setOnce: Properties = {}
    Object.entries((event.properties!['$set_once'] || {}) as Properties).forEach(([key, value]) => {
        if (!(key in set)) {
            setOnce[key] = value
        }
    })
    const unsetProps = event.properties!['$unset']
    const unset: string[] = (Array.isArray(unsetProps) ? unsetProps : Object.keys(unsetProps || {})).filter(
        (key): key is string => typeof key === 'string'
    )

    return {
        set,
        setOnce,
        unset,
        denied: false,
        shouldForceUpdate: PERSON_EVENTS.has(event.event) || updateAllProperties,
        eventName: event.event,
    }
}

/**
 * Refines extracted ops against a person-properties snapshot into the
 * Postgres write shape: set_once resolves locally (only absent keys
 * survive, as sets), sets are filtered to values that differ, unsets to
 * keys that exist, and the ignored-property rules decide whether the
 * surviving changes deserve a write. This is write-shape preparation for
 * a snapshot-based store — the personhog path never calls it; the leader
 * refines authoritatively on its side.
 */
export function refineEventOps(
    ops: EventOps,
    personProperties: Properties,
    updateAllProperties: boolean = false
): PropertyUpdates {
    if (ops.denied) {
        return { hasChanges: false, toSet: {}, toUnset: [], shouldForceUpdate: false }
    }

    let hasChanges = false
    let hasNonFilteredChanges = false
    const toSet: Properties = {}
    const toUnset: string[] = []
    const ignoredProperties: string[] = []

    Object.entries(ops.setOnce).forEach(([key, value]) => {
        if (typeof personProperties[key] === 'undefined') {
            hasChanges = true
            toSet[key] = value
            if (shouldUpdatePersonIfOnlyChange(ops, key, updateAllProperties)) {
                hasNonFilteredChanges = true
            }
        }
    })

    // First pass: detect if any property would trigger an update
    // If so, all changed properties in this $set should be updated together
    let anyPropertyTriggersUpdate = false
    const changedProperties: Array<[string, unknown]> = []

    Object.entries(ops.set).forEach(([key, value]) => {
        if (personProperties[key] !== value) {
            changedProperties.push([key, value])
            const isNewProperty = typeof personProperties[key] === 'undefined'
            if (isNewProperty || shouldUpdatePersonIfOnlyChange(ops, key, updateAllProperties)) {
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

    ops.unset.forEach((propertyKey) => {
        if (propertyKey in personProperties) {
            hasChanges = true
            hasNonFilteredChanges = true
            toUnset.push(propertyKey)
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

    return { hasChanges, toSet, toUnset, shouldForceUpdate: ops.shouldForceUpdate }
}

/**
 * Folds a later event's ops onto accumulated ops for the same person,
 * preserving sequential semantics per key: a set shadows any pending
 * set_once (the server applies set_once first, then set); among
 * set_onces the first wins; an unset clears both pending lanes; a set
 * after an unset supersedes it. Identity ORs and last-seen max-merges,
 * mirroring the leader's own merge rules.
 */
export function foldOps(existing: EventOps, incoming: EventOps): EventOps {
    if (incoming.denied) {
        return existing
    }
    if (existing.denied) {
        return incoming
    }

    const set = { ...existing.set }
    const setOnce = { ...existing.setOnce }
    const unset = new Set(existing.unset)

    Object.entries(incoming.setOnce).forEach(([key, value]) => {
        if (key in set || key in setOnce) {
            return
        }
        if (unset.has(key)) {
            // After an unset the key is definitely absent, so the
            // set_once becomes an unconditional set.
            unset.delete(key)
            set[key] = value
            return
        }
        setOnce[key] = value
    })

    Object.entries(incoming.set).forEach(([key, value]) => {
        set[key] = value
        delete setOnce[key]
        unset.delete(key)
    })

    incoming.unset.forEach((key) => {
        unset.add(key)
        delete set[key]
        delete setOnce[key]
    })

    return {
        set,
        setOnce,
        unset: [...unset],
        denied: false,
        shouldForceUpdate: existing.shouldForceUpdate || incoming.shouldForceUpdate,
        isIdentified: existing.isIdentified || incoming.isIdentified ? true : undefined,
        lastSeenAtMs:
            existing.lastSeenAtMs !== undefined || incoming.lastSeenAtMs !== undefined
                ? Math.max(existing.lastSeenAtMs ?? -Infinity, incoming.lastSeenAtMs ?? -Infinity)
                : undefined,
        eventName: incoming.eventName,
    }
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
function shouldUpdatePersonIfOnlyChange(ops: EventOps, key: string, updateAllProperties: boolean): boolean {
    if (updateAllProperties || ops.shouldForceUpdate) {
        // Person events and the update-all flag update everything
        return true
    }
    return !isFilteredPersonUpdateProperty(key)
}

import { DateTime } from 'luxon'

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
    /**
     * Whether any surviving change is one the ignored-property rules
     * count as update-worthy: a new key, an unset, a non-filtered value
     * change, or anything at all under force or update-all. False with
     * hasChanges true is the filtered-only shape a store may suppress.
     */
    hasNonFilteredChanges: boolean
}

/**
 * What one event asks of a person, extracted without consulting person
 * state: the ops as the event stated them. Interpretation of the event
 * (denylist, force semantics) happens here; what the ops mean given
 * current state is each store's concern. The Postgres store refines them
 * against its snapshot; the personhog store ships them for the leader to
 * resolve authoritatively.
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
 * surviving changes deserve a write. The personhog flush path never
 * calls this; the leader refines authoritatively on its side.
 */
/**
 * The scalar half of an op against current person state: identity ORs
 * (never reverts) and last-seen max-advances, the same merge the leader
 * performs. Returns only the fields that change, so callers can both
 * gate on "anything to write" and apply the delta. Deliberately
 * indifferent to `ops.denied`: the denylist gates property writes only.
 */
export function computeOpsScalarUpdates(ops: EventOps, person: InternalPerson): Partial<InternalPerson> {
    const updates: Partial<InternalPerson> = {}
    if (ops.isIdentified && !person.is_identified) {
        updates.is_identified = true
    }
    if (ops.lastSeenAtMs !== undefined) {
        const candidate = DateTime.fromMillis(ops.lastSeenAtMs, { zone: 'utc' })
        if (!person.last_seen_at || candidate > person.last_seen_at) {
            updates.last_seen_at = candidate
        }
    }
    return updates
}

export function refineEventOps(
    ops: EventOps,
    personProperties: Properties,
    updateAllProperties: boolean = false,
    recordOutcomes: boolean = true
): PropertyUpdates {
    if (ops.denied) {
        return { hasChanges: false, toSet: {}, toUnset: [], shouldForceUpdate: false, hasNonFilteredChanges: false }
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

    // Track person profile update outcomes at event level (skip when
    // updateAllProperties is enabled, or when the caller is projecting
    // rather than deciding a write — a projection re-refining the same
    // event must not double-count the outcome).
    if (!updateAllProperties && recordOutcomes) {
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

    return { hasChanges, toSet, toUnset, shouldForceUpdate: ops.shouldForceUpdate, hasNonFilteredChanges }
}

/**
 * Folds a later event's ops onto accumulated ops for the same person,
 * preserving sequential semantics per key: a set wins over any prior
 * state, the first set_once wins, an unset clears prior lanes, and a
 * value after an unset applies unconditionally (the key is definitely
 * absent). Identity ORs and last-seen max-merges, mirroring the leader's
 * merge rules.
 *
 * One event may pair an unset with a set or set_once of the same key.
 * Refinement resolves that pair against the snapshot (present means
 * gone, absent means the value lands), so the fold keeps both lanes as
 * a unit. A key's accumulated state is therefore a value, an unset, or
 * a snapshot-dependent pair.
 *
 * Returns null when composition would lose information: a later
 * set_once over a key already in the pair state needs "present resolves
 * one way, absent another with a different value", which no lane
 * combination expresses. The caller then cuts a segment, shipping the
 * accumulated ops as their own leader call so authoritative refinement
 * happens between the two.
 */
export function foldOps(existing: EventOps, incoming: EventOps): EventOps | null {
    if (incoming.denied || existing.denied) {
        // The denylist gates property writes only — identity and
        // last-seen advance regardless, matching both stores and the
        // leader. A denied op contributes its scalars and nothing else.
        const base = incoming.denied ? existing : incoming
        return {
            ...base,
            isIdentified: existing.isIdentified || incoming.isIdentified ? true : undefined,
            lastSeenAtMs: mergeLastSeenMs(existing.lastSeenAtMs, incoming.lastSeenAtMs),
        }
    }

    const states = keyStates(existing)
    for (const [key, op] of keyStates(incoming)) {
        const next = foldKey(states.get(key), op)
        if (next === null) {
            return null
        }
        states.set(key, next)
    }

    const set: Properties = {}
    const setOnce: Properties = {}
    const unset: string[] = []
    for (const [key, state] of states) {
        if (state.kind === 'unset' || state.kind === 'pair') {
            unset.push(key)
        }
        if (state.kind === 'value' || state.kind === 'pair') {
            ;(state.lane === 'set' ? set : setOnce)[key] = state.value
        }
    }

    return {
        set,
        setOnce,
        unset,
        denied: false,
        shouldForceUpdate: existing.shouldForceUpdate || incoming.shouldForceUpdate,
        isIdentified: existing.isIdentified || incoming.isIdentified ? true : undefined,
        lastSeenAtMs: mergeLastSeenMs(existing.lastSeenAtMs, incoming.lastSeenAtMs),
        eventName: incoming.eventName,
    }
}

/**
 * One key's accumulated (or incoming) state: a pending value in one of
 * the two lanes, a pending unset, or the snapshot-dependent pair of
 * both from a single event.
 */
type KeyState =
    | { kind: 'value'; lane: 'set' | 'setOnce'; value: unknown }
    | { kind: 'unset' }
    | { kind: 'pair'; lane: 'set' | 'setOnce'; value: unknown }

/** An EventOps decomposed per key, in set, setOnce, unset order. */
function keyStates(ops: EventOps): Map<string, KeyState> {
    const states = new Map<string, KeyState>()
    const unset = new Set(ops.unset)
    for (const [key, value] of Object.entries(ops.set)) {
        states.set(key, { kind: unset.has(key) ? 'pair' : 'value', lane: 'set', value })
    }
    for (const [key, value] of Object.entries(ops.setOnce)) {
        states.set(key, { kind: unset.has(key) ? 'pair' : 'value', lane: 'setOnce', value })
    }
    for (const key of ops.unset) {
        if (!states.has(key)) {
            states.set(key, { kind: 'unset' })
        }
    }
    return states
}

/**
 * The per-key transition table: what the accumulated state becomes when
 * a later event's op for the same key lands on it. `null` means the
 * composition is not representable and the caller must cut a segment.
 *
 * Two facts drive every row. A plain set or unset is unconditional, so
 * it supersedes whatever is pending. A set_once and a pair are
 * snapshot-dependent — set_once applies only where the key is absent,
 * a pair resolves to gone where present and to its value where absent —
 * so their outcome over pending state follows from what that state
 * guarantees about the key: a pending value guarantees present, a
 * pending unset guarantees absent, and a pending pair guarantees
 * nothing, which is why a snapshot-dependent op over it must segment.
 */
function foldKey(state: KeyState | undefined, op: KeyState): KeyState | null {
    if (op.kind === 'value' && op.lane === 'set') {
        return op
    }
    if (op.kind === 'unset') {
        return op
    }
    // op is a set_once or a pair; both resolve against the pending state.
    switch (state?.kind) {
        case undefined:
            return op
        case 'value':
            // Present is guaranteed: a set_once loses to the first
            // value, a pair resolves to gone.
            return op.kind === 'value' ? state : { kind: 'unset' }
        case 'unset':
            // Absent is guaranteed: either op's value applies
            // unconditionally.
            return { kind: 'value', lane: 'set', value: op.value }
        case 'pair':
            return null
    }
}

function mergeLastSeenMs(a: number | undefined, b: number | undefined): number | undefined {
    if (a === undefined && b === undefined) {
        return undefined
    }
    return Math.max(a ?? -Infinity, b ?? -Infinity)
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

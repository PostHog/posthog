import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt } from '~/types'

export interface PersonUpdate {
    id: string // bigint ID from database as string
    team_id: number
    uuid: string
    distinct_id: string
    properties: Properties // The properties this pod last read or landed
    properties_last_updated_at: PropertiesLastUpdatedAt
    properties_last_operation: PropertiesLastOperation
    created_at: DateTime
    /** The row version the base reflects, from the newest write answer or row read the entry has taken. */
    version: number
    is_identified: boolean
    is_user_id: number | null
    last_seen_at: DateTime | null
    needs_write: boolean
    // Fine-grained property tracking
    properties_to_set: Properties // Properties to set/update
    properties_to_set_once: Properties // Properties to set only where the row has none
    properties_to_unset: string[] // Property keys to unset
    original_is_identified: boolean
    original_created_at: DateTime
    original_last_seen_at: DateTime | null
    /** Set by a forcing event ($identify, $set); the next flush decision writes filtered keys with it, then resets it. */
    force_update?: boolean
    /** Set on a record a flush re-targeted after its person was merged away; its lanes are then the only carrier. */
    retargeted?: boolean
    /** Set on a record: the round that issued it, which is the only round whose write out its answer may clear. */
    issued?: Promise<void>
    /** The one write a flush decided for this entry whose answer is still out; no other is decided until it has. */
    in_flight?: InFlightWrite
}

export type PendingLanes = Pick<PersonUpdate, 'properties_to_set' | 'properties_to_set_once' | 'properties_to_unset'>

export interface InFlightWrite {
    /** What the write carries; a read applies these before the pending lanes. */
    lanes: PendingLanes
    /** The scalars the decision judged from, restored if the write hands its lanes back onto the same base. */
    originals: Pick<PersonUpdate, 'original_is_identified' | 'original_created_at' | 'original_last_seen_at'>
    /** The row version the decision judged against; the originals belong to that base and to no newer row. */
    version: number
    force: boolean
    /** Resolves once the flush that issued the write has processed its answer. */
    settled: Promise<void>
}

/** A merge's write to the survivor; `properties` holds only the keys to set. Identity and version are the row's. */
export type MergePersonUpdate = Omit<Partial<InternalPerson>, 'id' | 'uuid' | 'team_id' | 'version'> & {
    properties_to_set_once?: Properties
    properties_to_unset?: string[]
}

export type PendingPersonChanges = { toSet: Properties; toSetOnce: Properties; toUnset: string[]; createdAt: DateTime }

export interface PersonPropertyUpdate {
    updated: boolean
    properties: Properties
    properties_last_updated_at: PropertiesLastUpdatedAt
    properties_last_operation: PropertiesLastOperation
}

export function fromInternalPerson(person: InternalPerson, distinctId: string): PersonUpdate {
    return {
        id: person.id,
        team_id: person.team_id,
        uuid: person.uuid,
        distinct_id: distinctId,
        properties: person.properties,
        properties_last_updated_at: person.properties_last_updated_at,
        properties_last_operation: person.properties_last_operation || {},
        created_at: person.created_at,
        version: person.version,
        is_identified: person.is_identified,
        is_user_id: person.is_user_id,
        last_seen_at: person.last_seen_at,
        needs_write: false,
        properties_to_set: {},
        properties_to_set_once: {},
        properties_to_unset: [],
        original_is_identified: person.is_identified,
        original_created_at: person.created_at,
        original_last_seen_at: person.last_seen_at,
        force_update: false, // Default to false, can be set to true by $identify/$set events
    }
}

export function toInternalPerson(personUpdate: PersonUpdate): InternalPerson {
    // The view: the base, then the write out, then the lanes still pending.
    const finalProperties = { ...personUpdate.properties }
    const lanes = personUpdate.in_flight ? [personUpdate.in_flight.lanes, personUpdate] : [personUpdate]
    for (const lane of lanes) {
        for (const [key, value] of Object.entries(lane.properties_to_set_once)) {
            if (!Object.hasOwn(finalProperties, key)) {
                finalProperties[key] = value
            }
        }
        for (const [key, value] of Object.entries(lane.properties_to_set)) {
            finalProperties[key] = value
        }
        for (const key of lane.properties_to_unset) {
            delete finalProperties[key]
        }
    }

    return {
        id: personUpdate.id, // Use the actual database ID, not the UUID
        uuid: personUpdate.uuid,
        team_id: personUpdate.team_id,
        properties: finalProperties,
        properties_last_updated_at: personUpdate.properties_last_updated_at,
        properties_last_operation: personUpdate.properties_last_operation,
        created_at: personUpdate.created_at,
        version: personUpdate.version,
        is_identified: personUpdate.is_identified,
        is_user_id: personUpdate.is_user_id,
        last_seen_at: personUpdate.last_seen_at,
    }
}

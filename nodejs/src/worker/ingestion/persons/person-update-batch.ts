import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { InternalPerson, PersonGroupKeys, PropertiesLastOperation, PropertiesLastUpdatedAt } from '../../../types'

export interface PersonUpdate extends PersonGroupKeys {
    id: string // bigint ID from database as string
    team_id: number
    uuid: string
    distinct_id: string
    properties: Properties // Original properties from database
    properties_last_updated_at: PropertiesLastUpdatedAt
    properties_last_operation: PropertiesLastOperation
    created_at: DateTime
    version: number
    is_identified: boolean
    is_user_id: number | null
    needs_write: boolean
    // Fine-grained property tracking
    properties_to_set: Properties // Properties to set/update
    properties_to_unset: string[] // Property keys to unset
    original_is_identified: boolean
    original_created_at: DateTime
    /** If true, bypass batch-level filtering for person property updates (set for $identify, $set, etc.) */
    force_update?: boolean
    /** Group keys to update (from event $groups) */
    group_keys_to_set?: Partial<PersonGroupKeys>
}

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
        needs_write: false,
        properties_to_set: {},
        properties_to_unset: [],
        original_is_identified: person.is_identified,
        original_created_at: person.created_at,
        force_update: false, // Default to false, can be set to true by $identify/$set events
        // Copy group keys from person
        group_0_key: person.group_0_key || '',
        group_1_key: person.group_1_key || '',
        group_2_key: person.group_2_key || '',
        group_3_key: person.group_3_key || '',
        group_4_key: person.group_4_key || '',
    }
}

export function toInternalPerson(personUpdate: PersonUpdate): InternalPerson {
    // Calculate final properties by applying set and unset operations
    const finalProperties = { ...personUpdate.properties }

    // Apply properties to set
    Object.entries(personUpdate.properties_to_set).forEach(([key, value]) => {
        finalProperties[key] = value
    })

    // Apply properties to unset
    personUpdate.properties_to_unset.forEach((key) => {
        delete finalProperties[key]
    })

    // Apply group keys to set (merge with existing)
    let group_0_key = personUpdate.group_0_key
    let group_1_key = personUpdate.group_1_key
    let group_2_key = personUpdate.group_2_key
    let group_3_key = personUpdate.group_3_key
    let group_4_key = personUpdate.group_4_key

    if (personUpdate.group_keys_to_set) {
        if (personUpdate.group_keys_to_set.group_0_key !== undefined) {
            group_0_key = personUpdate.group_keys_to_set.group_0_key
        }
        if (personUpdate.group_keys_to_set.group_1_key !== undefined) {
            group_1_key = personUpdate.group_keys_to_set.group_1_key
        }
        if (personUpdate.group_keys_to_set.group_2_key !== undefined) {
            group_2_key = personUpdate.group_keys_to_set.group_2_key
        }
        if (personUpdate.group_keys_to_set.group_3_key !== undefined) {
            group_3_key = personUpdate.group_keys_to_set.group_3_key
        }
        if (personUpdate.group_keys_to_set.group_4_key !== undefined) {
            group_4_key = personUpdate.group_keys_to_set.group_4_key
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
        group_0_key,
        group_1_key,
        group_2_key,
        group_3_key,
        group_4_key,
    }
}

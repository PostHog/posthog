import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt } from '../../../types'

export interface PersonUpdate {
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
    }
}

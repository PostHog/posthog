import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt } from '../../../types'

export interface PersonUpdate {
    id: string // bigint ID from database as string
    team_id: number
    uuid: string
    distinct_id: string
    properties: Properties
    properties_last_updated_at: PropertiesLastUpdatedAt
    properties_last_operation: PropertiesLastOperation
    created_at: DateTime
    version: number
    is_identified: boolean
    is_user_id: number | null
    needs_write: boolean
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
    }
}

export function toInternalPerson(personUpdate: PersonUpdate): InternalPerson {
    return {
        id: personUpdate.id, // Use the actual database ID, not the UUID
        uuid: personUpdate.uuid,
        team_id: personUpdate.team_id,
        properties: personUpdate.properties,
        properties_last_updated_at: personUpdate.properties_last_updated_at,
        properties_last_operation: personUpdate.properties_last_operation,
        created_at: personUpdate.created_at,
        version: personUpdate.version,
        is_identified: personUpdate.is_identified,
        is_user_id: personUpdate.is_user_id,
    }
}

export function calculatePersonPropertyUpdate(
    currentProperties: Properties,
    currentPropertiesLastUpdatedAt: PropertiesLastUpdatedAt,
    currentPropertiesLastOperation: PropertiesLastOperation,
    propertiesToSet: Properties,
    propertiesToUnset: string[],
    _timestamp: DateTime
): PersonPropertyUpdate {
    const result: PersonPropertyUpdate = {
        updated: false,
        properties: { ...currentProperties },
        properties_last_updated_at: { ...currentPropertiesLastUpdatedAt },
        properties_last_operation: { ...currentPropertiesLastOperation },
    }

    // Set new properties
    Object.entries(propertiesToSet).forEach(([key, value]) => {
        if (!(key in result.properties) || value !== result.properties[key]) {
            result.updated = true
            result.properties[key] = value
        }
    })

    // Unset properties
    propertiesToUnset.forEach((propertyKey) => {
        if (propertyKey in result.properties) {
            result.updated = true
            delete result.properties[propertyKey]
        }
    })

    return result
}

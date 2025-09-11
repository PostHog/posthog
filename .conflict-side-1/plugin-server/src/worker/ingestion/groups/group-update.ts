import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { Group, GroupTypeIndex, TeamId } from '../../../types'

export interface GroupUpdate {
    team_id: TeamId
    group_type_index: GroupTypeIndex
    group_key: string
    group_properties: Properties
    created_at: DateTime
    version: number
    needsWrite: boolean
}

export interface PropertiesUpdate {
    updated: boolean
    properties: Properties
}

export function fromGroup(group: Group): GroupUpdate {
    return {
        team_id: group.team_id,
        group_type_index: group.group_type_index,
        group_key: group.group_key,
        group_properties: group.group_properties,
        created_at: group.created_at,
        version: group.version,
        needsWrite: false,
    }
}

export function calculateUpdate(currentProperties: Properties, properties: Properties): PropertiesUpdate {
    const result: PropertiesUpdate = {
        updated: false,
        properties: { ...currentProperties },
    }

    // Ideally we'd keep track of event timestamps, for when properties were updated
    // and only update the values if a newer timestamped event set them.
    // However to do that we would need to keep track of previous set timestamps,
    // which means that even if the property value didn't change
    // we would need to trigger an update to update the timestamps.
    // This can kill Postgres if someone sends us lots of groupidentify events.
    // So instead we just process properties updates based on ingestion time,
    // i.e. always update if value has changed.
    Object.entries(properties).forEach(([key, value]) => {
        if (!(key in result.properties) || value != result.properties[key]) {
            result.updated = true
            result.properties[key] = value
        }
    })
    return result
}

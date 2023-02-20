import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Group, GroupTypeIndex, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { RaceConditionError } from '../../utils/utils'

interface PropertiesUpdate {
    updated: boolean
    properties: Properties
}

export async function upsertGroup(
    db: DB,
    teamId: TeamId,
    groupTypeIndex: GroupTypeIndex,
    groupKey: string,
    properties: Properties,
    timestamp: DateTime
): Promise<void> {
    try {
        const [propertiesUpdate, createdAt, version] = await db.postgresTransaction('upsertGroup', async (client) => {
            const group: Group | undefined = await db.fetchGroup(teamId, groupTypeIndex, groupKey, client, {
                forUpdate: true,
            })
            const createdAt = DateTime.min(group?.created_at || DateTime.now(), timestamp)
            const version = (group?.version || 0) + 1

            const propertiesUpdate = calculateUpdate(group?.group_properties || {}, properties)

            if (!group) {
                propertiesUpdate.updated = true
            }

            if (propertiesUpdate.updated) {
                if (group) {
                    await db.updateGroup(
                        teamId,
                        groupTypeIndex,
                        groupKey,
                        propertiesUpdate.properties,
                        createdAt,
                        version,
                        client
                    )
                } else {
                    // :TRICKY: insertGroup will raise a RaceConditionError if group was inserted in-between fetch and this
                    await db.insertGroup(
                        teamId,
                        groupTypeIndex,
                        groupKey,
                        propertiesUpdate.properties,
                        createdAt,
                        version,
                        client
                    )
                }
            }

            return [propertiesUpdate, createdAt, version]
        })

        if (propertiesUpdate.updated) {
            await db.upsertGroupClickhouse(
                teamId,
                groupTypeIndex,
                groupKey,
                propertiesUpdate.properties,
                createdAt,
                version
            )
        }
    } catch (error) {
        if (error instanceof RaceConditionError) {
            // Try again - lock the row and insert!
            return upsertGroup(db, teamId, groupTypeIndex, groupKey, properties, timestamp)
        }
        throw error
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
            ;(result.updated = true), (result.properties[key] = value)
        }
    })
    return result
}

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
                        {},
                        {},
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
                        {},
                        {},
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

    // We always update properties at ingestion time and ignore the timestamps events sent
    Object.entries(properties).forEach(([key, value]) => {
        if (!(key in result.properties) || value != result.properties[key]) {
            ;(result.updated = true), (result.properties[key] = value)
        }
    })
    return result
}

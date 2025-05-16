import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Group, GroupTypeIndex, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { groupUpdateVersionMismatchCounter } from '../../utils/db/metrics'
import { PostgresUse } from '../../utils/db/postgres'
import { logger } from '../../utils/logger'
import { RaceConditionError } from '../../utils/utils'
import { captureIngestionWarning } from './utils'

interface PropertiesUpdate {
    updated: boolean
    properties: Properties
}

export async function upsertGroup(
    db: DB,
    teamId: TeamId,
    projectId: TeamId,
    groupTypeIndex: GroupTypeIndex,
    groupKey: string,
    properties: Properties,
    timestamp: DateTime,
    forUpdate: boolean = true
): Promise<void> {
    try {
        const [propertiesUpdate, createdAt, version] = await db.postgres.transaction(
            PostgresUse.COMMON_WRITE,
            'upsertGroup',
            async (tx) => {
                const group: Group | undefined = await db.fetchGroup(teamId, groupTypeIndex, groupKey, tx, {
                    forUpdate,
                })
                const createdAt = DateTime.min(group?.created_at || DateTime.now(), timestamp)
                const version = (group?.version || 0) + 1

                const propertiesUpdate = calculateUpdate(group?.group_properties || {}, properties)

                if (!group) {
                    propertiesUpdate.updated = true
                }

                if (propertiesUpdate.updated) {
                    if (group) {
                        const updatedVersion = await db.updateGroup(
                            teamId,
                            groupTypeIndex,
                            groupKey,
                            propertiesUpdate.properties,
                            createdAt,
                            {},
                            {},
                            version,
                            tx
                        )
                        if (updatedVersion !== undefined) {
                            // Track the disparity between the version on the database and the version we computed
                            // Without races, the returned version should be only +1 what we computed
                            const versionDisparity = updatedVersion - version
                            if (versionDisparity > 0) {
                                logger.info('👥', 'Group update version mismatch', {
                                    team_id: teamId,
                                    group_type_index: groupTypeIndex,
                                    group_key: groupKey,
                                    version_disparity: versionDisparity,
                                })
                                groupUpdateVersionMismatchCounter.labels({ type: 'version_mismatch' }).inc()
                            }
                        } else {
                            logger.info('👥', 'Group update row missing', {
                                team_id: teamId,
                                group_type_index: groupTypeIndex,
                                group_key: groupKey,
                            })
                            groupUpdateVersionMismatchCounter.labels({ type: 'row_missing' }).inc()
                        }
                    } else {
                        // :TRICKY: insertGroup will raise a RaceConditionError if group was inserted in-between fetch and this
                        const insertedVersion = await db.insertGroup(
                            teamId,
                            groupTypeIndex,
                            groupKey,
                            propertiesUpdate.properties,
                            createdAt,
                            {},
                            {},
                            version,
                            tx
                        )
                        // Track the disparity between the version on the database and the version we computed
                        // Without races, the returned version should be only +1 what we computed
                        const versionDisparity = insertedVersion - version
                        if (versionDisparity > 0) {
                            logger.info('👥', 'Group update version mismatch', {
                                team_id: teamId,
                                group_type_index: groupTypeIndex,
                                group_key: groupKey,
                                version_disparity: versionDisparity,
                            })
                            groupUpdateVersionMismatchCounter.labels({ type: 'version_mismatch' }).inc()
                        }
                    }
                }

                return [propertiesUpdate, createdAt, version]
            }
        )

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
        if (error instanceof MessageSizeTooLarge) {
            // Message is too large, for kafka - this is unrecoverable so we capture an ingestion warning instead
            await captureIngestionWarning(db.kafkaProducer, teamId, 'group_upsert_message_size_too_large', {
                groupTypeIndex,
                groupKey,
            })
            return
        }
        if (error instanceof RaceConditionError) {
            // Try again - lock the row and insert!
            return upsertGroup(db, teamId, projectId, groupTypeIndex, groupKey, properties, timestamp)
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

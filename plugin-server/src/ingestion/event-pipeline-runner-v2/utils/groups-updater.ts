import { DateTime } from 'luxon'

import { KAFKA_GROUPS } from '../../../config/kafka-topics'
import { MessageSizeTooLarge } from '../../../kafka/producer'
import { GroupTypeIndex, Hub, Properties, RawGroup, TeamId, TimestampFormat } from '../../../types'
import { captureIngestionWarning } from '../../../utils/ingestion-warnings'
import { PostgresUse } from '../../../utils/postgres'
import { castTimestampOrNow, RaceConditionError } from '../../../utils/utils'
interface PropertiesUpdate {
    updated: boolean
    properties: Properties
}
export async function upsertGroup(
    hub: Hub,
    teamId: TeamId,
    projectId: TeamId,
    groupTypeIndex: GroupTypeIndex,
    groupKey: string,
    properties: Properties,
    timestamp: DateTime
): Promise<void> {
    try {
        const [propertiesUpdate, createdAt, version] = await hub.postgres.transaction(
            PostgresUse.COMMON_WRITE,
            'upsertGroup',
            async (tx) => {
                const selectResult = await hub.postgres.query<RawGroup>(
                    tx,
                    `SELECT * FROM posthog_group WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3  FOR UPDATE`,
                    [teamId, groupTypeIndex, groupKey],
                    'fetchGroup'
                )

                const rawGroup = selectResult.rows.length > 0 ? selectResult.rows[0] : undefined

                const group = rawGroup
                    ? {
                          ...rawGroup,
                          created_at: DateTime.fromISO(rawGroup.created_at).toUTC(),
                          version: Number(rawGroup.version || 0),
                      }
                    : undefined

                const createdAt = DateTime.min(group?.created_at || DateTime.now(), timestamp)
                const version = (group?.version || 0) + 1

                const propertiesUpdate = calculateUpdate(group?.group_properties || {}, properties)

                if (!group) {
                    propertiesUpdate.updated = true
                }

                if (propertiesUpdate.updated) {
                    if (group) {
                        await hub.postgres.query(
                            tx,
                            `
                            UPDATE posthog_group SET
                            created_at = $4,
                            group_properties = $5,
                            properties_last_updated_at = $6,
                            properties_last_operation = $7,
                            version = $8
                            WHERE team_id = $1 AND group_key = $2 AND group_type_index = $3
                            `,
                            [
                                teamId,
                                groupKey,
                                groupTypeIndex,
                                createdAt.toISO(),
                                JSON.stringify(propertiesUpdate.properties),
                                JSON.stringify({}),
                                JSON.stringify({}),
                                version,
                            ],
                            'upsertGroup'
                        )
                    } else {
                        const result = await hub.postgres.query(
                            tx ?? PostgresUse.COMMON_WRITE,
                            `
                            INSERT INTO posthog_group (team_id, group_key, group_type_index, group_properties, created_at, properties_last_updated_at, properties_last_operation, version)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            ON CONFLICT (team_id, group_key, group_type_index) DO NOTHING
                            RETURNING version
                            `,
                            [
                                teamId,
                                groupKey,
                                groupTypeIndex,
                                JSON.stringify(propertiesUpdate.properties),
                                createdAt.toISO(),
                                JSON.stringify({}),
                                JSON.stringify({}),
                                version,
                            ],
                            'upsertGroup'
                        )

                        // :TRICKY: Raise a RaceConditionError if group was inserted in-between fetch and this
                        if (result.rows.length === 0) {
                            throw new RaceConditionError('Parallel posthog_group inserts, retry')
                        }
                    }
                }

                return [propertiesUpdate, createdAt, version]
            }
        )

        if (propertiesUpdate.updated) {
            await hub.kafkaProducer.queueMessages({
                topic: KAFKA_GROUPS,
                messages: [
                    {
                        value: JSON.stringify({
                            group_type_index: groupTypeIndex,
                            group_key: groupKey,
                            team_id: teamId,
                            group_properties: JSON.stringify(properties),
                            created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouseSecondPrecision),
                            version,
                        }),
                    },
                ],
            })
        }
    } catch (error) {
        if (error instanceof MessageSizeTooLarge) {
            // Message is too large, for kafka - this is unrecoverable so we capture an ingestion warning instead
            await captureIngestionWarning(hub.kafkaProducer, teamId, 'group_upsert_message_size_too_large', {
                groupTypeIndex,
                groupKey,
            })
            return
        }
        if (error instanceof RaceConditionError) {
            // Try again - lock the row and insert!
            return upsertGroup(hub, teamId, projectId, groupTypeIndex, groupKey, properties, timestamp)
        }
        throw error
    }
}

function calculateUpdate(currentProperties: Properties, properties: Properties): PropertiesUpdate {
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

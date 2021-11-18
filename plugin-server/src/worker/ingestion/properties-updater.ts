import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { QueryResult } from 'pg'

import {
    Group,
    GroupTypeIndex,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    PropertyUpdateOperation,
    TeamId,
} from '../../types'
import { DB } from '../../utils/db/db'
import { generateKafkaPersonUpdateMessage } from '../../utils/db/utils'
import { RaceConditionError } from '../../utils/utils'

interface PropertiesUpdate {
    updated: boolean
    properties: Properties
    properties_last_updated_at: PropertiesLastUpdatedAt
    properties_last_operation: PropertiesLastOperation
}

export async function updatePersonProperties(
    db: DB,
    teamId: TeamId,
    distinctId: string,
    properties: Properties,
    propertiesOnce: Properties,
    timestamp: DateTime
): Promise<void> {
    if (Object.keys(properties).length === 0 && Object.keys(propertiesOnce).length === 0) {
        return
    }

    const [propertiesUpdate, person] = await db.postgresTransaction(async (client) => {
        const person = await db.fetchPerson(teamId, distinctId, client, { forUpdate: true })
        if (!person) {
            throw new Error(
                `Could not find person with distinct id "${distinctId}" in team "${teamId}" to update props`
            )
        }

        const propertiesUpdate: PropertiesUpdate = calculateUpdate(
            person.properties,
            properties,
            propertiesOnce,
            person.properties_last_updated_at,
            person.properties_last_operation || {},
            timestamp
        )
        if (propertiesUpdate.updated) {
            const updateResult: QueryResult = await db.postgresQuery(
                `UPDATE posthog_person SET
                    properties = $1,
                    properties_last_updated_at = $2,
                    properties_last_operation = $3,
                    version = COALESCE(version, 0)::numeric + 1
                WHERE id = $4
                RETURNING version`,
                [
                    JSON.stringify(propertiesUpdate.properties),
                    JSON.stringify(propertiesUpdate.properties_last_updated_at),
                    JSON.stringify(propertiesUpdate.properties_last_operation),
                    person.id,
                ],
                'updatePersonProperties',
                client
            )
            person.version = Number(updateResult.rows[0].version)
        }
        return [propertiesUpdate, person]
    })

    if (db.kafkaProducer && propertiesUpdate.updated) {
        const kafkaMessage = generateKafkaPersonUpdateMessage(
            timestamp,
            propertiesUpdate.properties,
            person.team_id,
            person.is_identified,
            person.uuid,
            person.version
        )
        await db.kafkaProducer.queueMessage(kafkaMessage)
    }
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
        const [propertiesUpdate, createdAt, version] = await db.postgresTransaction(async (client) => {
            const group: Group | undefined = await db.fetchGroup(teamId, groupTypeIndex, groupKey, client, {
                forUpdate: true,
            })
            const createdAt = group?.created_at || timestamp
            const version = (group?.version || 0) + 1

            const propertiesUpdate = calculateUpdate(
                group?.group_properties || {},
                properties,
                {},
                group?.properties_last_updated_at || {},
                group?.properties_last_operation || {},
                timestamp
            )

            if (!group) {
                propertiesUpdate.updated = true
            }

            if (propertiesUpdate.updated) {
                // :TRICKY: insertGroup will raise a RaceConditionError if group was inserted in-between fetch and this
                const upsertMethod = group ? 'updateGroup' : 'insertGroup'
                await db[upsertMethod](
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    propertiesUpdate.properties,
                    createdAt,
                    propertiesUpdate.properties_last_updated_at,
                    propertiesUpdate.properties_last_operation,
                    version,
                    client
                )
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

export function calculateUpdate(
    currentProperties: Properties,
    properties: Properties,
    propertiesOnce: Properties,
    propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
    propertiesLastOperation: PropertiesLastOperation,
    timestamp: DateTime
): PropertiesUpdate {
    const result: PropertiesUpdate = {
        updated: false,
        properties: { ...currentProperties },
        properties_last_updated_at: { ...propertiesLastUpdatedAt },
        properties_last_operation: { ...propertiesLastOperation },
    }

    Object.entries(propertiesOnce).forEach(([key, value]) => {
        if (
            !(key in result.properties) ||
            (getPropertiesLastOperationOrSet(propertiesLastOperation, key) === PropertyUpdateOperation.SetOnce &&
                getPropertyLastUpdatedAtDateTimeOrEpoch(propertiesLastUpdatedAt, key) > timestamp)
        ) {
            result.updated = true
            result.properties[key] = value
            result.properties_last_operation[key] = PropertyUpdateOperation.SetOnce
            result.properties_last_updated_at[key] = timestamp.toISO()
        }
    })
    // note that if the key appears twice we override it with set value here
    Object.entries(properties).forEach(([key, value]) => {
        if (
            !(key in result.properties) ||
            getPropertiesLastOperationOrSet(propertiesLastOperation, key) === PropertyUpdateOperation.SetOnce ||
            getPropertyLastUpdatedAtDateTimeOrEpoch(propertiesLastUpdatedAt, key) < timestamp
        ) {
            result.updated = true
            result.properties[key] = value
            result.properties_last_operation[key] = PropertyUpdateOperation.Set
            result.properties_last_updated_at[key] = timestamp.toISO()
        }
    })
    return result
}

function getPropertyLastUpdatedAtDateTimeOrEpoch(
    propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
    key: string
): DateTime {
    const lookup = propertiesLastUpdatedAt[key]
    if (lookup) {
        return DateTime.fromISO(lookup)
    }
    return DateTime.fromMillis(0)
}

function getPropertiesLastOperationOrSet(
    propertiesLastOperation: PropertiesLastOperation,
    key: string
): PropertyUpdateOperation {
    if (!(key in propertiesLastOperation)) {
        return PropertyUpdateOperation.Set
    }
    return propertiesLastOperation[key]
}

import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { QueryResult } from 'pg'

import {
    Person,
    PersonPropertyUpdateOperation,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    TeamId,
} from '../../types'
import { DB } from '../../utils/db/db'
import { generateKafkaPersonUpdateMessage } from '../../utils/db/utils'

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
        const person = await db.fetchPerson(teamId, distinctId, client, true)
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
            (getPropertiesLastOperationOrSet(propertiesLastOperation, key) === PersonPropertyUpdateOperation.SetOnce &&
                getPropertyLastUpdatedAtDateTimeOrEpoch(propertiesLastUpdatedAt, key) > timestamp)
        ) {
            result.updated = true
            result.properties[key] = value
            result.properties_last_operation[key] = PersonPropertyUpdateOperation.SetOnce
            result.properties_last_updated_at[key] = timestamp.toISO()
        }
    })
    // note that if the key appears twice we override it with set value here
    Object.entries(properties).forEach(([key, value]) => {
        if (
            !(key in result.properties) ||
            getPropertiesLastOperationOrSet(propertiesLastOperation, key) === PersonPropertyUpdateOperation.SetOnce ||
            getPropertyLastUpdatedAtDateTimeOrEpoch(propertiesLastUpdatedAt, key) < timestamp
        ) {
            result.updated = true
            result.properties[key] = value
            result.properties_last_operation[key] = PersonPropertyUpdateOperation.Set
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
): PersonPropertyUpdateOperation {
    if (!(key in propertiesLastOperation)) {
        return PersonPropertyUpdateOperation.Set
    }
    return propertiesLastOperation[key]
}

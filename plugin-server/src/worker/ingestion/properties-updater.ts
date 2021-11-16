import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { QueryResult } from 'pg'

import { Person, PersonPropertyUpdateOperation, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { generateKafkaPersonUpdateMessage } from '../../utils/db/utils'

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

    let person: Person | undefined
    await db.postgresTransaction(async (client) => {
        person = await db.fetchPerson(teamId, distinctId, client, true)
        if (!person) {
            throw new Error(
                `Could not find person with distinct id "${distinctId}" in team "${teamId}" to update props`
            )
        }

        const shouldUpdate = calculateUpdatedProperties(person, properties, propertiesOnce, timestamp)
        if (!shouldUpdate) {
            return
        }

        const updateResult: QueryResult = await db.postgresQuery(
            `UPDATE posthog_person SET
                properties = $1,
                properties_last_updated_at = $2,
                properties_last_operation = $3,
                version = COALESCE(version, 0)::numeric + 1
            WHERE id = $4
            RETURNING version`,
            [
                JSON.stringify(person.properties),
                JSON.stringify(person.properties_last_updated_at),
                JSON.stringify(person.properties_last_operation || {}),
                person.id,
            ],
            'updatePersonProperties',
            client
        )
        person.version = Number(updateResult.rows[0].version)
    })

    if (db.kafkaProducer && person) {
        const kafkaMessage = generateKafkaPersonUpdateMessage(
            timestamp,
            person.properties,
            person.team_id,
            person.is_identified,
            person.uuid,
            person.version
        )
        await db.kafkaProducer.queueMessage(kafkaMessage)
    }
}

export function calculateUpdatedProperties(
    person: Person,
    properties: Properties,
    propertiesOnce: Properties,
    timestamp: DateTime
): boolean {
    // :TRICKY: This mutates the person object & returns true/false if anything was updated
    let updatedSomething = false
    Object.entries(propertiesOnce).forEach(([key, value]) => {
        if (
            !(key in person.properties) ||
            (getPropertiesLastOperationOrSet(person, key) === PersonPropertyUpdateOperation.SetOnce &&
                getPropertyLastUpdatedAtDateTimeOrEpoch(person, key) > timestamp)
        ) {
            updatedSomething = true
            person.properties[key] = value
            updatePropertiesLastOperation(person, key, PersonPropertyUpdateOperation.SetOnce)
            person.properties_last_updated_at[key] = timestamp.toISO()
        }
    })
    // note that if the key appears twice we override it with set value here
    Object.entries(properties).forEach(([key, value]) => {
        if (
            !(key in person.properties) ||
            getPropertiesLastOperationOrSet(person, key) === PersonPropertyUpdateOperation.SetOnce ||
            getPropertyLastUpdatedAtDateTimeOrEpoch(person, key) < timestamp
        ) {
            updatedSomething = true
            person.properties[key] = value
            updatePropertiesLastOperation(person, key, PersonPropertyUpdateOperation.Set)
            person.properties_last_updated_at[key] = timestamp.toISO()
        }
    })
    return updatedSomething
}

function getPropertyLastUpdatedAtDateTimeOrEpoch(person: Person, key: string): DateTime {
    const lookup = person.properties_last_updated_at[key]
    if (lookup) {
        return DateTime.fromISO(lookup)
    }
    return DateTime.fromMillis(0)
}

function getPropertiesLastOperationOrSet(person: Person, key: string): PersonPropertyUpdateOperation {
    if (!person.properties_last_operation || !(key in person.properties_last_operation)) {
        return PersonPropertyUpdateOperation.Set
    }
    return person.properties_last_operation[key]
}

function updatePropertiesLastOperation(person: Person, key: string, value: PersonPropertyUpdateOperation) {
    if (!person.properties_last_operation) {
        person.properties_last_operation = {}
    }
    person.properties_last_operation[key] = value
}

import { TopicMessage } from '../../../../kafka/producer'
import { InternalPerson, RawPerson } from '../../../../types'
import { generateKafkaPersonUpdateMessage, sanitizeJsonbValue } from '../../../../utils/db/utils'
import { NoRowsUpdatedError } from '../../../../utils/utils'
import { PersonUpdate } from '../person-update-batch'
import { PersonPropertiesSizeViolationError } from './person-repository'

/** Prepared arrays for batch update UNNEST queries */
export interface BatchUpdateArrays {
    uuids: string[]
    teamIds: number[]
    properties: string[]
    propertiesLastUpdatedAt: string[]
    propertiesLastOperation: string[]
    isIdentified: boolean[]
    createdAt: string[]
}

/** Result of a batch update operation for a single person */
export interface BatchUpdateResult {
    success: boolean
    version?: number
    kafkaMessage?: TopicMessage
    error?: Error
}

/**
 * Prepare arrays for batch update UNNEST queries.
 * Calculates final properties by applying set and unset operations.
 */
export function prepareBatchUpdateArrays(personUpdates: PersonUpdate[]): BatchUpdateArrays {
    const arrays: BatchUpdateArrays = {
        uuids: [],
        teamIds: [],
        properties: [],
        propertiesLastUpdatedAt: [],
        propertiesLastOperation: [],
        isIdentified: [],
        createdAt: [],
    }

    for (const update of personUpdates) {
        arrays.uuids.push(update.uuid)
        arrays.teamIds.push(update.team_id)

        // Calculate final properties by applying set and unset operations
        const finalProperties = { ...update.properties }
        Object.entries(update.properties_to_set).forEach(([key, value]) => {
            finalProperties[key] = value
        })
        update.properties_to_unset.forEach((key) => {
            delete finalProperties[key]
        })

        arrays.properties.push(sanitizeJsonbValue(finalProperties))
        arrays.propertiesLastUpdatedAt.push(sanitizeJsonbValue(update.properties_last_updated_at))
        arrays.propertiesLastOperation.push(sanitizeJsonbValue(update.properties_last_operation))
        arrays.isIdentified.push(update.is_identified)
        arrays.createdAt.push(update.created_at.toISO()!)
    }

    return arrays
}

/**
 * Process batch update results and build the result map.
 */
export function processBatchUpdateResults(
    personUpdates: PersonUpdate[],
    rows: RawPerson[],
    isVersionAssert: boolean,
    toPerson: (row: RawPerson) => InternalPerson
): Map<string, BatchUpdateResult> {
    const results = new Map<string, BatchUpdateResult>()

    // Build a map of uuid -> updated person for quick lookup
    const updatedPersonsByUuid = new Map<string, InternalPerson>()
    for (const row of rows) {
        const person = toPerson(row)
        updatedPersonsByUuid.set(person.uuid, person)
    }

    // Process results for each input update
    for (const update of personUpdates) {
        const updatedPerson = updatedPersonsByUuid.get(update.uuid)
        if (updatedPerson) {
            results.set(update.uuid, {
                success: true,
                version: updatedPerson.version,
                kafkaMessage: generateKafkaPersonUpdateMessage(updatedPerson),
            })
        } else {
            // Person was not found/updated
            const errorMessage = isVersionAssert
                ? `Person with uuid="${update.uuid}" version mismatch (expected ${update.version})`
                : `Person with uuid="${update.uuid}" and team_id="${update.team_id}" was not updated`
            results.set(update.uuid, {
                success: false,
                error: new NoRowsUpdatedError(errorMessage),
            })
        }
    }

    return results
}

/**
 * Handle batch update errors and populate the results map.
 */
export function handleBatchUpdateError(
    personUpdates: PersonUpdate[],
    error: unknown,
    isPropertiesSizeConstraintViolation: (error: unknown) => boolean
): Map<string, BatchUpdateResult> {
    const results = new Map<string, BatchUpdateResult>()

    if (isPropertiesSizeConstraintViolation(error)) {
        for (const update of personUpdates) {
            results.set(update.uuid, {
                success: false,
                error: new PersonPropertiesSizeViolationError(
                    `Batch update failed due to properties size constraint`,
                    update.team_id,
                    update.id
                ),
            })
        }
    } else {
        for (const update of personUpdates) {
            results.set(update.uuid, {
                success: false,
                error: error instanceof Error ? error : new Error(String(error)),
            })
        }
    }

    return results
}

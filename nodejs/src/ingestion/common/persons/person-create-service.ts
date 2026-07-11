import { DateTime } from 'luxon'

import { PersonMessage } from '~/common/persons/person-message'
import { PersonPropertiesSizeViolationError } from '~/common/persons/repositories/person-repository'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { uuidFromDistinctId } from '~/ingestion/common/persons/person-uuid'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertyUpdateOperation } from '~/types'

import { PersonContext } from './person-context'
import { PersonsStoreTransactionForBatch } from './persons-store-for-batch'

export class PersonCreateService {
    constructor(private context: PersonContext) {}

    /**
     * @returns [Person, whether this call created the person (false when a concurrent creation
     * won), and the Kafka messages for the creation. Messages are returned instead of produced
     * here so callers control when the produce happens: outside any wrapping Postgres transaction,
     * and without awaiting the delivery report inline — a backpressured producer would otherwise
     * stall the sequential per-distinct-id lane (and hold the transaction open in merge paths).]
     */
    async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesOnce: Properties,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        creatorEventUuid: string,
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds?: { distinctId: string; version?: number }[],
        tx?: PersonsStoreTransactionForBatch
    ): Promise<[InternalPerson, boolean, PersonMessage[]]> {
        const uuid = uuidFromDistinctId(teamId, primaryDistinctId.distinctId)

        const props = { ...propertiesOnce, ...properties, ...{ $creator_event_uuid: creatorEventUuid } }
        const propertiesLastOperation: Record<string, any> = {}
        const propertiesLastUpdatedAt: Record<string, any> = {}
        Object.keys(propertiesOnce).forEach((key) => {
            propertiesLastOperation[key] = PropertyUpdateOperation.SetOnce
            propertiesLastUpdatedAt[key] = createdAt.toISO()
        })
        Object.keys(properties).forEach((key) => {
            propertiesLastOperation[key] = PropertyUpdateOperation.Set
            propertiesLastUpdatedAt[key] = createdAt.toISO()
        })

        try {
            const result = await (tx || this.context.personStore).createPerson(
                createdAt,
                props,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                teamId,
                isUserId,
                isIdentified,
                uuid,
                primaryDistinctId,
                extraDistinctIds
            )

            if (result.success) {
                return [result.person, result.created, result.messages]
            }

            // Handle creation conflict - another process created the person concurrently
            if (result.error === 'CreationConflict') {
                // Try to fetch the person that was created concurrently
                const allDistinctIds = [primaryDistinctId, ...(extraDistinctIds || [])]
                for (const distinctIdInfo of allDistinctIds) {
                    const existingPerson = await this.context.personStore.fetchForUpdate(
                        teamId,
                        distinctIdInfo.distinctId
                    )
                    if (existingPerson) {
                        return [existingPerson, false, []]
                    }
                }

                // If we still can't find the person, something is wrong
                throw new Error(
                    `Person creation failed with constraint violation, but could not fetch existing person for distinct IDs: ${result.distinctIds.join(
                        ', '
                    )}`
                )
            }

            // This should never happen due to the discriminated union, but TypeScript requires it
            throw new Error('Unexpected CreatePersonResult state')
        } catch (error) {
            if (error instanceof PersonPropertiesSizeViolationError) {
                await emitIngestionWarning(this.context.outputs, teamId, {
                    type: 'person_properties_size_violation',
                    details: {
                        // uuid of the person we tried to create; error.personId is a DB row id
                        personId: uuid,
                        distinctId: primaryDistinctId.distinctId,
                        teamId: teamId,
                        eventUuid: creatorEventUuid,
                        message: 'Person properties exceeds size limit and was rejected',
                    },
                    pipelineStep: 'person-store',
                })
                throw error
            }

            // Re-throw other errors
            throw error
        }
    }
}

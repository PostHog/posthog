import { DateTime } from 'luxon'

import { personCreateConflictResolvedCounter } from '~/common/persons/metrics'
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
     * @returns [Person, boolean that indicates if person was created or not, true if person was created by this call, false if found existing person from concurrent creation]
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
    ): Promise<[InternalPerson, boolean]> {
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
                await this.context.produceMessages(result.messages)
                return [result.person, result.created]
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
                        return [existingPerson, false]
                    }
                }

                // Nothing owns the distinct IDs we tried to create, so the row holding this
                // uuid owns a different one. Resolve to it: the alternative is an error with no
                // isRetriable, which the pipeline rethrows until the consumer dies with
                // uncommitted offsets. The event is attributed to the holder without moving any
                // mapping, so no two identities are silently merged.
                if (result.conflictingPerson) {
                    personCreateConflictResolvedCounter.labels({ resolved_by: 'uuid' }).inc()
                    return [result.conflictingPerson, false]
                }

                // The holder vanished between the failed write and the lookup, so there is
                // nothing to resolve to.
                personCreateConflictResolvedCounter.labels({ resolved_by: 'none' }).inc()
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

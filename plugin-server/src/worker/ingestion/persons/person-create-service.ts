import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { InternalPerson, PropertyUpdateOperation } from '../../../types'
import { uuidFromDistinctId } from '../person-uuid'
import { captureIngestionWarning } from '../utils'
import { PersonContext } from './person-context'
import { PersonsStoreTransaction } from './persons-store-transaction'
import { PersonPropertiesSizeViolationError } from './repositories/person-repository'

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
        distinctIds: { distinctId: string; version?: number }[],
        tx?: PersonsStoreTransaction
    ): Promise<[InternalPerson, boolean]> {
        if (distinctIds.length < 1) {
            throw new Error('at least 1 distinctId is required in `createPerson`')
        }

        const uuid = uuidFromDistinctId(teamId, distinctIds[0].distinctId)

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
                distinctIds
            )

            if (result.success) {
                await this.context.kafkaProducer.queueMessages(result.messages)
                return [result.person, result.created]
            }

            // Handle creation conflict - another process created the person concurrently
            if (result.error === 'CreationConflict') {
                // Try to fetch the person that was created concurrently
                for (const distinctIdInfo of distinctIds) {
                    const existingPerson = await this.context.personStore.fetchForUpdate(
                        teamId,
                        distinctIdInfo.distinctId
                    )
                    if (existingPerson) {
                        return [existingPerson, false]
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
                await captureIngestionWarning(this.context.kafkaProducer, teamId, 'person_properties_size_violation', {
                    personId: error.personId,
                    distinctId: distinctIds[0]?.distinctId,
                    teamId: teamId,
                    message: 'Person properties exceeds size limit and was rejected',
                })
                throw error
            }

            // Re-throw other errors
            throw error
        }
    }
}

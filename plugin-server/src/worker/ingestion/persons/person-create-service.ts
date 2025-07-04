import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { InternalPerson, PropertyUpdateOperation } from '../../../types'
import { TransactionClient } from '../../../utils/db/postgres'
import { uuidFromDistinctId } from '../person-uuid'
import { PersonContext } from './person-context'

export class PersonCreateService {
    constructor(private context: PersonContext) {}

    async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesOnce: Properties,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        creatorEventUuid: string,
        distinctIds: { distinctId: string; version?: number }[],
        tx?: TransactionClient
    ): Promise<InternalPerson> {
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

        const [person, kafkaMessages] = await this.context.personStore.createPerson(
            createdAt,
            props,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            distinctIds,
            tx
        )

        await this.context.kafkaProducer.queueMessages(kafkaMessages)
        return person
    }
}

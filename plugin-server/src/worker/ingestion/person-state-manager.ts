import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Person, PropertyUpdateOperation } from '../../types'
import { DB } from '../../utils/db/db'
import { UUIDT } from '../../utils/utils'

// This class is responsible for creating/updating a single person through the process-event pipeline
export class PersonStateManager {
    timestamp: DateTime
    newUuid: string

    private db: DB

    constructor(timestamp: DateTime, db: DB) {
        this.timestamp = timestamp
        this.newUuid = new UUIDT().toString()

        this.db = db
    }

    async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesOnce: Properties,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        distinctIds?: string[]
    ): Promise<Person> {
        const props = { ...propertiesOnce, ...properties }
        const propertiesLastOperation: Record<string, any> = {}
        const propertiesLastUpdatedAt: Record<string, any> = {}
        Object.keys(propertiesOnce).forEach((key) => {
            propertiesLastOperation[key] = PropertyUpdateOperation.SetOnce
            propertiesLastUpdatedAt[key] = createdAt
        })
        Object.keys(properties).forEach((key) => {
            propertiesLastOperation[key] = PropertyUpdateOperation.Set
            propertiesLastUpdatedAt[key] = createdAt
        })

        return await this.db.createPerson(
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
    }
}

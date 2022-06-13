import { Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'

import { Person, PropertyUpdateOperation } from '../../types'
import { DB } from '../../utils/db/db'
import { UUIDT } from '../../utils/utils'
import { PersonManager } from './person-manager'

// This class is responsible for creating/updating a single person through the process-event pipeline
export class PersonStateManager {
    timestamp: DateTime
    newUuid: string

    private db: DB
    private personManager: PersonManager

    constructor(timestamp: DateTime, db: DB, personManager: PersonManager) {
        this.timestamp = timestamp
        this.newUuid = new UUIDT().toString()

        this.db = db
        this.personManager = personManager
    }

    async createPersonIfDistinctIdIsNew(
        teamId: number,
        distinctId: string,
        timestamp: DateTime,
        personUuid: string,
        properties?: Properties,
        propertiesOnce?: Properties
    ): Promise<boolean> {
        const isNewPerson = await this.personManager.isNewPerson(this.db, teamId, distinctId)
        if (isNewPerson) {
            // Catch race condition where in between getting and creating, another request already created this user
            try {
                await this.createPerson(
                    timestamp,
                    properties || {},
                    propertiesOnce || {},
                    teamId,
                    null,
                    false,
                    personUuid.toString(),
                    [distinctId]
                )
                return true
            } catch (error) {
                if (!error.message || !error.message.includes('duplicate key value violates unique constraint')) {
                    Sentry.captureException(error, { extra: { teamId, distinctId, timestamp, personUuid } })
                }
            }
        }
        return false
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

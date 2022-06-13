import { Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import equal from 'fast-deep-equal'
import { StatsD } from 'hot-shots'
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
    private statsd: StatsD | undefined
    private personManager: PersonManager

    constructor(timestamp: DateTime, db: DB, statsd: StatsD | undefined, personManager: PersonManager) {
        this.timestamp = timestamp
        this.newUuid = new UUIDT().toString()

        this.db = db
        this.statsd = statsd
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

    async updatePersonProperties(
        teamId: number,
        distinctId: string,
        properties: Properties,
        propertiesOnce: Properties,
        unsetProperties: Array<string>
    ): Promise<void> {
        const personFound = await this.db.fetchPerson(teamId, distinctId)
        if (!personFound) {
            this.statsd?.increment('person_not_found', { teamId: String(teamId), key: 'update' })
            throw new Error(
                `Could not find person with distinct id "${distinctId}" in team "${teamId}" to update properties`
            )
        }

        // Figure out which properties we are actually setting
        const updatedProperties: Properties = { ...personFound.properties }
        Object.entries(propertiesOnce).map(([key, value]) => {
            if (typeof personFound?.properties[key] === 'undefined') {
                updatedProperties[key] = value
            }
        })
        Object.entries(properties).map(([key, value]) => {
            if (personFound?.properties[key] !== value) {
                updatedProperties[key] = value
            }
        })

        unsetProperties.forEach((propertyKey) => {
            delete updatedProperties[propertyKey]
        })

        const arePersonsEqual = equal(personFound.properties, updatedProperties)

        if (arePersonsEqual) {
            return
        }

        await this.db.updatePersonDeprecated(personFound, { properties: updatedProperties })
    }
}

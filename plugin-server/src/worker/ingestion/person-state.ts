import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import equal from 'fast-deep-equal'
import { StatsD } from 'hot-shots'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { DatabaseError, PoolClient } from 'pg'

import { Person, PropertyUpdateOperation } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { UUIDT } from '../../utils/utils'
import { PersonManager } from './person-manager'

const MAX_FAILED_PERSON_MERGE_ATTEMPTS = 3

// used to prevent identify from being used with generic IDs
// that we can safely assume stem from a bug or mistake
const CASE_INSENSITIVE_ILLEGAL_IDS = new Set([
    'anonymous',
    'guest',
    'distinctid',
    'distinct_id',
    'id',
    'not_authenticated',
    'email',
    'undefined',
    'true',
    'false',
])

const CASE_SENSITIVE_ILLEGAL_IDS = new Set(['[object Object]', 'NaN', 'None', 'none', 'null', '0'])

const isDistinctIdIllegal = (id: string): boolean => {
    return id.trim() === '' || CASE_INSENSITIVE_ILLEGAL_IDS.has(id.toLowerCase()) || CASE_SENSITIVE_ILLEGAL_IDS.has(id)
}

// This class is responsible for creating/updating a single person through the process-event pipeline
export class PersonState {
    event: PluginEvent
    distinctId: string
    teamId: number
    eventProperties: Properties
    timestamp: DateTime
    newUuid: string

    person: Person | undefined

    private db: DB
    private statsd: StatsD | undefined
    private personManager: PersonManager
    private updateIsIdentified: boolean

    constructor(
        event: PluginEvent,
        teamId: number,
        distinctId: string,
        timestamp: DateTime,
        db: DB,
        statsd: StatsD | undefined,
        personManager: PersonManager,
        person: Person | undefined = undefined,
        uuid: UUIDT | undefined = undefined
    ) {
        this.event = event
        this.distinctId = distinctId
        this.teamId = teamId
        this.eventProperties = event.properties!
        this.timestamp = timestamp
        this.newUuid = (uuid || new UUIDT()).toString()

        this.db = db
        this.statsd = statsd
        this.personManager = personManager

        // Used to avoid unneeded person fetches.
        // :KLUDGE: May change through `handleIdentifyOrAlias` flow on merges/create person
        this.person = person

        // If set to true, we'll update `is_identified` at the end of `updateProperties`
        // :KLUDGE: This is an indirect communication channel between `handleIdentifyOrAlias` and `updateProperties`
        this.updateIsIdentified = false
    }

    async update(): Promise<Person | undefined> {
        await this.handleIdentifyOrAlias()
        return await this.updateProperties()
    }

    async updateProperties(): Promise<Person | undefined> {
        let result: Person | undefined = this.person
        let personCreated = false
        if (!result) {
            result = await this.createPersonIfDistinctIdIsNew()
            personCreated = !!result
        }
        if (
            !personCreated &&
            (this.eventProperties['$set'] ||
                this.eventProperties['$set_once'] ||
                this.eventProperties['$unset'] ||
                this.updateIsIdentified)
        ) {
            result = await this.updatePersonProperties()
        }
        return result
    }

    private async createPersonIfDistinctIdIsNew(): Promise<Person | undefined> {
        const isNewPerson = await this.personManager.isNewPerson(this.db, this.teamId, this.distinctId)
        if (isNewPerson) {
            const properties = this.eventProperties['$set'] || {}
            const propertiesOnce = this.eventProperties['$set_once'] || {}
            // Catch race condition where in between getting and creating, another request already created this user
            try {
                return await this.createPerson(
                    this.timestamp,
                    properties || {},
                    propertiesOnce || {},
                    this.teamId,
                    null,
                    // :NOTE: This should never be set in this branch, but adding this for logical consistency
                    this.updateIsIdentified,
                    this.newUuid,
                    [this.distinctId]
                )
            } catch (error) {
                if (!error.message || !error.message.includes('duplicate key value violates unique constraint')) {
                    Sentry.captureException(error, {
                        extra: {
                            teamId: this.teamId,
                            distinctId: this.distinctId,
                            timestamp: this.timestamp,
                            personUuid: this.newUuid,
                        },
                    })
                }
            }
        }
        return undefined
    }

    private async createPerson(
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

    private async updatePersonProperties(): Promise<Person> {
        // Note: In majority of cases person has been found already here!
        const personFound = this.person || (await this.db.fetchPerson(this.teamId, this.distinctId))
        if (!personFound) {
            this.statsd?.increment('person_not_found', { teamId: String(this.teamId), key: 'update' })
            throw new Error(
                `Could not find person with distinct id "${this.distinctId}" in team "${this.teamId}" to update properties`
            )
        }
        const update: Partial<Person> = {}
        const updatedProperties = this.updatedPersonProperties(personFound.properties || {})

        if (!equal(personFound.properties, updatedProperties)) {
            update.properties = updatedProperties
        }
        if (this.updateIsIdentified && !personFound.is_identified) {
            update.is_identified = true
        }

        if (Object.keys(update).length > 0) {
            const [updatedPerson] = await this.db.updatePersonDeprecated(personFound, update)
            return updatedPerson
        } else {
            return personFound
        }
    }

    private updatedPersonProperties(personProperties: Properties): Properties {
        const updatedProperties = { ...personProperties }

        const properties: Properties = this.eventProperties['$set'] || {}
        const propertiesOnce: Properties = this.eventProperties['$set_once'] || {}
        const unsetProperties: Array<string> = this.eventProperties['$unset'] || []

        // Figure out which properties we are actually setting
        Object.entries(propertiesOnce).map(([key, value]) => {
            if (typeof personProperties[key] === 'undefined') {
                updatedProperties[key] = value
            }
        })
        Object.entries(properties).map(([key, value]) => {
            if (personProperties[key] !== value) {
                updatedProperties[key] = value
            }
        })

        unsetProperties.forEach((propertyKey) => {
            delete updatedProperties[propertyKey]
        })

        return updatedProperties
    }

    // Alias & merge

    async handleIdentifyOrAlias(): Promise<void> {
        if (isDistinctIdIllegal(this.distinctId)) {
            this.statsd?.increment(`illegal_distinct_ids.total`, { distinctId: this.distinctId })
            return
        }

        const timeout = timeoutGuard('Still running "handleIdentifyOrAlias". Timeout warning after 30 sec!')
        try {
            if (this.event.event === '$create_alias') {
                await this.merge(this.eventProperties['alias'], this.distinctId, this.teamId, this.timestamp, false)
            } else if (this.event.event === '$identify' && this.eventProperties['$anon_distinct_id']) {
                await this.merge(
                    this.eventProperties['$anon_distinct_id'],
                    this.distinctId,
                    this.teamId,
                    this.timestamp,
                    true
                )
            }
        } catch (e) {
            console.error('handleIdentifyOrAlias failed', e, this.event)
        } finally {
            clearTimeout(timeout)
        }
    }

    private async merge(
        previousDistinctId: string,
        distinctId: string,
        teamId: number,
        timestamp: DateTime,
        isIdentifyCall: boolean
    ): Promise<void> {
        // No reason to alias person against itself. Done by posthog-js-lite when updating user properties
        if (distinctId === previousDistinctId) {
            return
        }
        await this.aliasDeprecated(previousDistinctId, distinctId, teamId, timestamp, isIdentifyCall)
    }

    private async aliasDeprecated(
        previousDistinctId: string,
        distinctId: string,
        teamId: number,
        timestamp: DateTime,
        shouldIdentifyPerson = true,
        retryIfFailed = true,
        totalMergeAttempts = 0
    ): Promise<void> {
        // No reason to alias person against itself. Done by posthog-js-lite when updating user properties
        if (previousDistinctId === distinctId) {
            return
        }

        const oldPerson = await this.db.fetchPerson(teamId, previousDistinctId)
        // :TRICKY: Reduce needless lookups for person
        this.person = this.person || (await this.db.fetchPerson(teamId, distinctId))
        const newPerson = this.person

        if (oldPerson && !newPerson) {
            try {
                await this.db.addDistinctId(oldPerson, distinctId)
                this.updateIsIdentified = shouldIdentifyPerson
                // Catch race case when somebody already added this distinct_id between .get and .addDistinctId
            } catch {
                // integrity error
                if (retryIfFailed) {
                    // run everything again to merge the users if needed
                    await this.aliasDeprecated(
                        previousDistinctId,
                        distinctId,
                        teamId,
                        timestamp,
                        shouldIdentifyPerson,
                        false
                    )
                }
            }
        } else if (!oldPerson && newPerson) {
            try {
                await this.db.addDistinctId(newPerson, previousDistinctId)
                this.updateIsIdentified = shouldIdentifyPerson
                // Catch race case when somebody already added this distinct_id between .get and .addDistinctId
            } catch {
                // integrity error
                if (retryIfFailed) {
                    // run everything again to merge the users if needed
                    await this.aliasDeprecated(
                        previousDistinctId,
                        distinctId,
                        teamId,
                        timestamp,
                        shouldIdentifyPerson,
                        false
                    )
                }
            }
        } else if (!oldPerson && !newPerson) {
            try {
                const person = await this.createPerson(
                    timestamp,
                    this.eventProperties['$set'] || {},
                    this.eventProperties['$set_once'] || {},
                    teamId,
                    null,
                    shouldIdentifyPerson,
                    this.newUuid,
                    [distinctId, previousDistinctId]
                )
                // :KLUDGE: Avoid unneeded fetches in updateProperties()
                this.person = person
            } catch {
                // Catch race condition where in between getting and creating,
                // another request already created this person
                if (retryIfFailed) {
                    // Try once more, probably one of the two persons exists now
                    await this.aliasDeprecated(
                        previousDistinctId,
                        distinctId,
                        teamId,
                        timestamp,
                        shouldIdentifyPerson,
                        false
                    )
                }
            }
        } else if (oldPerson && newPerson && oldPerson.id !== newPerson.id) {
            // $create_alias is an explicit call to merge 2 users, so we'll merge anything
            // for $identify, we'll not merge a user who's already identified into anyone else
            const isIdentifyCallToMergeAnIdentifiedUser = shouldIdentifyPerson && oldPerson.is_identified

            if (isIdentifyCallToMergeAnIdentifiedUser) {
                status.warn('🤔', 'refused to merge an already identified user via an $identify call')
                this.updateIsIdentified = shouldIdentifyPerson
            } else {
                await this.mergePeople({
                    totalMergeAttempts,
                    shouldIdentifyPerson,
                    mergeInto: newPerson,
                    mergeIntoDistinctId: distinctId,
                    otherPerson: oldPerson,
                    otherPersonDistinctId: previousDistinctId,
                    timestamp: timestamp,
                })
            }
        } else {
            this.updateIsIdentified = shouldIdentifyPerson
        }
    }

    public async mergePeople({
        mergeInto,
        mergeIntoDistinctId,
        otherPerson,
        otherPersonDistinctId,
        timestamp,
        totalMergeAttempts = 0,
        shouldIdentifyPerson = true,
    }: {
        mergeInto: Person
        mergeIntoDistinctId: string
        otherPerson: Person
        otherPersonDistinctId: string
        timestamp: DateTime
        totalMergeAttempts: number
        shouldIdentifyPerson?: boolean
    }): Promise<void> {
        const teamId = mergeInto.team_id

        let firstSeen = mergeInto.created_at

        // Merge properties
        mergeInto.properties = { ...otherPerson.properties, ...mergeInto.properties }
        if (otherPerson.created_at < firstSeen) {
            // Keep the oldest created_at (i.e. the first time we've seen this person)
            firstSeen = otherPerson.created_at
        }

        let kafkaMessages: ProducerRecord[] = []

        let failedAttempts = totalMergeAttempts

        // Retrying merging up to `MAX_FAILED_PERSON_MERGE_ATTEMPTS` times, in case race conditions occur.
        // An example is a distinct ID being aliased in another plugin server instance,
        // between `moveDistinctId` and `deletePerson` being called here
        // – in such a case a distinct ID may be assigned to the person in the database
        // AFTER `otherPersonDistinctIds` was fetched, so this function is not aware of it and doesn't merge it.
        // That then causes `deletePerson` to fail, because of foreign key constraints –
        // the dangling distinct ID added elsewhere prevents the person from being deleted!
        // This is low-probability so likely won't occur on second retry of this block.
        // In the rare case of the person changing VERY often however, it may happen even a few times,
        // in which case we'll bail and rethrow the error.
        await this.db.postgresTransaction(async (client) => {
            try {
                const [person, updatePersonMessages] = await this.db.updatePersonDeprecated(
                    mergeInto,
                    {
                        created_at: firstSeen,
                        properties: this.updatedPersonProperties(mergeInto.properties),
                        is_identified: mergeInto.is_identified || otherPerson.is_identified || shouldIdentifyPerson,
                    },
                    client
                )

                // :KLUDGE: Avoid unneeded fetches in updateProperties()
                this.person = person

                // Merge the distinct IDs
                await this.handleTablesDependingOnPersonID(otherPerson, mergeInto, client)

                const distinctIdMessages = await this.db.moveDistinctIds(otherPerson, mergeInto, client)

                const deletePersonMessages = await this.db.deletePerson(otherPerson, client)

                kafkaMessages = [...updatePersonMessages, ...distinctIdMessages, ...deletePersonMessages]
            } catch (error) {
                if (!(error instanceof DatabaseError)) {
                    throw error // Very much not OK, this is some completely unexpected error
                }

                failedAttempts++
                if (failedAttempts === MAX_FAILED_PERSON_MERGE_ATTEMPTS) {
                    throw error // Very much not OK, failed repeatedly so rethrowing the error
                }

                await this.aliasDeprecated(
                    otherPersonDistinctId,
                    mergeIntoDistinctId,
                    teamId,
                    timestamp,
                    shouldIdentifyPerson,
                    false,
                    failedAttempts
                )
            }
        })

        await this.db.kafkaProducer.queueMessages(kafkaMessages)
    }

    private async handleTablesDependingOnPersonID(
        sourcePerson: Person,
        targetPerson: Person,
        client?: PoolClient
    ): Promise<void> {
        // When personIDs change, update places depending on a person_id foreign key

        // For Cohorts
        await this.db.postgresQuery(
            'UPDATE posthog_cohortpeople SET person_id = $1 WHERE person_id = $2',
            [targetPerson.id, sourcePerson.id],
            'updateCohortPeople',
            client
        )

        // For FeatureFlagHashKeyOverrides
        await this.db.addFeatureFlagHashKeysForMergedPerson(sourcePerson.team_id, sourcePerson.id, targetPerson.id)
    }
}

// Helper functions to ease mocking in tests
export function updatePersonState(...params: ConstructorParameters<typeof PersonState>): Promise<Person | undefined> {
    return new PersonState(...params).update()
}

export function updatePropertiesPersonState(
    ...params: ConstructorParameters<typeof PersonState>
): Promise<Person | undefined> {
    return new PersonState(...params).updateProperties()
}

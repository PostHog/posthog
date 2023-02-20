import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import equal from 'fast-deep-equal'
import { StatsD } from 'hot-shots'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { PoolClient } from 'pg'

import { KAFKA_PERSON_OVERRIDE } from '../../config/kafka-topics'
import { Person, PropertyUpdateOperation } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { NoRowsUpdatedError, UUIDT } from '../../utils/utils'
import { LazyPersonContainer } from './lazy-person-container'
import { PersonManager } from './person-manager'
import { captureIngestionWarning } from './utils'

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

const CASE_SENSITIVE_ILLEGAL_IDS = new Set(['[object Object]', 'NaN', 'None', 'none', 'null', '0', 'undefined'])

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

    personContainer: LazyPersonContainer

    private db: DB
    private statsd: StatsD | undefined
    private personManager: PersonManager
    private updateIsIdentified: boolean
    private poEEmbraceJoin: boolean

    constructor(
        event: PluginEvent,
        teamId: number,
        distinctId: string,
        timestamp: DateTime,
        db: DB,
        statsd: StatsD | undefined,
        personManager: PersonManager,
        personContainer: LazyPersonContainer,
        poEEmbraceJoin: boolean,
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

        // Used to avoid unneeded person fetches and to respond with updated person details
        // :KLUDGE: May change through these flows.
        this.personContainer = personContainer

        // If set to true, we'll update `is_identified` at the end of `updateProperties`
        // :KLUDGE: This is an indirect communication channel between `handleIdentifyOrAlias` and `updateProperties`
        this.updateIsIdentified = false

        // For persons on events embrace the join gradual roll-out, remove after fully rolled out
        this.poEEmbraceJoin = poEEmbraceJoin
    }

    async update(): Promise<LazyPersonContainer> {
        await this.handleIdentifyOrAlias()
        await this.updateProperties()
        return this.personContainer
    }

    async updateProperties(): Promise<LazyPersonContainer> {
        const personCreated = await this.createPersonIfDistinctIdIsNew()
        if (
            !personCreated &&
            (this.eventProperties['$set'] ||
                this.eventProperties['$set_once'] ||
                this.eventProperties['$unset'] ||
                this.updateIsIdentified)
        ) {
            const person = await this.updatePersonProperties()
            if (person) {
                this.personContainer = this.personContainer.with(person)
            }
        }
        return this.personContainer
    }

    private async createPersonIfDistinctIdIsNew(): Promise<boolean> {
        // :TRICKY: Short-circuit if person container already has loaded person and it exists
        if (this.personContainer.loaded) {
            return false
        }

        const isNewPerson = await this.personManager.isNewPerson(this.db, this.teamId, this.distinctId)
        if (isNewPerson) {
            const properties = this.eventProperties['$set'] || {}
            const propertiesOnce = this.eventProperties['$set_once'] || {}
            // Catch race condition where in between getting and creating, another request already created this user
            try {
                const person = await this.createPerson(
                    this.timestamp,
                    properties || {},
                    propertiesOnce || {},
                    this.teamId,
                    null,
                    // :NOTE: This should never be set in this branch, but adding this for logical consistency
                    this.updateIsIdentified,
                    this.newUuid,
                    this.event.uuid,
                    [this.distinctId]
                )
                // :TRICKY: Avoid subsequent queries re-fetching person
                this.personContainer = this.personContainer.with(person)
                return true
            } catch (error) {
                status.error('🚨', 'create_person_failed', { error, teamId: this.teamId, distinctId: this.distinctId })
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

        // Person was likely created in-between start-of-processing and now, so ensure that subsequent queries
        // to fetch person still return the right `person`
        this.personContainer = this.personContainer.reset()
        return false
    }

    private async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesOnce: Properties,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        creatorEventUuid: string,
        distinctIds?: string[]
    ): Promise<Person> {
        const props = { ...propertiesOnce, ...properties, ...{ $creator_event_uuid: creatorEventUuid } }
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

    private async updatePersonProperties(): Promise<Person | null> {
        try {
            return await this.tryUpdatePerson()
        } catch (error) {
            // :TRICKY: Handle race where user might have been merged between start of processing and now
            //      As we only allow anonymous -> identified merges, only need to do this once.
            if (error instanceof NoRowsUpdatedError) {
                this.personContainer = this.personContainer.reset()
                return await this.tryUpdatePerson()
            } else {
                throw error
            }
        }
    }

    private async tryUpdatePerson(): Promise<Person | null> {
        // Note: In majority of cases person has been found already here!
        const personFound = await this.personContainer.get()
        if (!personFound) {
            this.statsd?.increment('person_not_found', { teamId: String(this.teamId), key: 'update' })
            throw new Error(
                `Could not find person with distinct id "${this.distinctId}" in team "${this.teamId}" to update properties`
            )
        }

        const update: Partial<Person> = {}
        const updatedProperties = this.applyEventPropertyUpdates(personFound.properties || {})

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
            return null
        }
    }

    private applyEventPropertyUpdates(personProperties: Properties): Properties {
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
        /**
         * strategy:
         *   - if the two distinct ids passed don't match and aren't illegal, then mark `is_identified` to be true for the `distinct_id` person
         *   - if a person doesn't exist for either distinct id passed we create the person with both ids
         *   - if only one person exists we add the other distinct id
         *   - if the distinct ids belong to different already existing persons we try to merge them:
         *     - the merge is blocked if the other distinct id (`anon_distinct_id` or `alias` event property) person has `is_identified` true.
         *     - we merge into `distinct_id` person:
         *       - both distinct ids used in the future will map to the person id that was associated with `distinct_id` before
         *       - if person property was defined for both we'll use `distinct_id` person's property going forward
         */
        const timeout = timeoutGuard('Still running "handleIdentifyOrAlias". Timeout warning after 30 sec!')
        try {
            if (this.event.event === '$create_alias' && this.eventProperties['alias']) {
                await this.merge(
                    String(this.eventProperties['alias']),
                    this.distinctId,
                    this.teamId,
                    this.timestamp,
                    false
                )
            } else if (this.event.event === '$identify' && this.eventProperties['$anon_distinct_id']) {
                await this.merge(
                    String(this.eventProperties['$anon_distinct_id']),
                    this.distinctId,
                    this.teamId,
                    this.timestamp,
                    true
                )
            }
        } catch (e) {
            console.error('handleIdentifyOrAlias failed', e, this.event)

            throw e
        } finally {
            clearTimeout(timeout)
        }
    }

    public async merge(
        previousDistinctId: string,
        distinctId: string,
        teamId: number,
        timestamp: DateTime,
        isIdentifyCall: boolean
    ): Promise<void> {
        // No reason to alias person against itself. Done by posthog-node when updating user properties
        if (distinctId === previousDistinctId) {
            return
        }
        if (isDistinctIdIllegal(distinctId)) {
            this.statsd?.increment('illegal_distinct_ids.total', { distinctId: distinctId })
            captureIngestionWarning(this.db, teamId, 'cannot_merge_with_illegal_distinct_id', {
                illegalDistinctId: distinctId,
                otherDistinctId: previousDistinctId,
            })
            return
        }
        if (isDistinctIdIllegal(previousDistinctId)) {
            this.statsd?.increment('illegal_distinct_ids.total', { distinctId: previousDistinctId })
            captureIngestionWarning(this.db, teamId, 'cannot_merge_with_illegal_distinct_id', {
                illegalDistinctId: previousDistinctId,
                otherDistinctId: distinctId,
            })
            return
        }
        await this.mergeWithoutValidation(previousDistinctId, distinctId, teamId, timestamp, isIdentifyCall, 0)
    }

    private async mergeWithoutValidation(
        previousDistinctId: string,
        distinctId: string,
        teamId: number,
        timestamp: DateTime,
        isIdentifyCall = true,
        totalMergeAttempts = 0
    ): Promise<void> {
        // No reason to alias person against itself. Done by posthog-node when updating user properties
        if (previousDistinctId === distinctId) {
            return
        }

        this.updateIsIdentified = true

        const oldPerson = await this.db.fetchPerson(teamId, previousDistinctId)
        // :TRICKY: Reduce needless lookups for person
        const newPerson = await this.personContainer.get()

        try {
            if (oldPerson && !newPerson) {
                await this.db.addDistinctId(oldPerson, distinctId)
                this.personContainer = this.personContainer.with(oldPerson)
            } else if (!oldPerson && newPerson) {
                await this.db.addDistinctId(newPerson, previousDistinctId)
            } else if (!oldPerson && !newPerson) {
                const person = await this.createPerson(
                    timestamp,
                    this.eventProperties['$set'] || {},
                    this.eventProperties['$set_once'] || {},
                    teamId,
                    null,
                    true,
                    this.newUuid,
                    this.event.uuid,
                    [distinctId, previousDistinctId]
                )
                // :KLUDGE: Avoid unneeded fetches in updateProperties()
                this.personContainer = this.personContainer.with(person)
            } else if (oldPerson && newPerson && oldPerson.id !== newPerson.id) {
                await this.mergePeople({
                    shouldIdentifyPerson: isIdentifyCall,
                    mergeInto: newPerson,
                    mergeIntoDistinctId: distinctId,
                    otherPerson: oldPerson,
                    otherPersonDistinctId: previousDistinctId,
                })
            }
        } catch (error) {
            // Retrying merging up to `MAX_FAILED_PERSON_MERGE_ATTEMPTS` times, in case race conditions occur.
            // E.g. Catch race case when somebody already added this distinct_id between .get and .addDistinctId
            // E.g. Catch race condition where in between getting and creating, another request already created this person
            // An example is a distinct ID being aliased in another plugin server instance,
            // between `moveDistinctId` and `deletePerson` being called here
            // – in such a case a distinct ID may be assigned to the person in the database
            // AFTER `otherPersonDistinctIds` was fetched, so this function is not aware of it and doesn't merge it.
            // That then causes `deletePerson` to fail, because of foreign key constraints –
            // the dangling distinct ID added elsewhere prevents the person from being deleted!
            // This is low-probability so likely won't occur on second retry of this block.
            // In the rare case of the person changing VERY often however, it may happen even a few times,
            // in which case we'll bail and rethrow the error.
            totalMergeAttempts++
            if (totalMergeAttempts >= MAX_FAILED_PERSON_MERGE_ATTEMPTS) {
                throw error // Very much not OK, failed repeatedly so rethrowing the error
            }
            await this.mergeWithoutValidation(
                previousDistinctId,
                distinctId,
                teamId,
                timestamp,
                isIdentifyCall,
                totalMergeAttempts
            )
        }
    }

    public async mergePeople({
        mergeInto,
        mergeIntoDistinctId,
        otherPerson,
        otherPersonDistinctId,
        shouldIdentifyPerson = true,
    }: {
        mergeInto: Person
        mergeIntoDistinctId: string
        otherPerson: Person
        otherPersonDistinctId: string
        shouldIdentifyPerson?: boolean
    }): Promise<void> {
        const olderCreatedAt = DateTime.min(mergeInto.created_at, otherPerson.created_at)
        const newerCreatedAt = DateTime.max(mergeInto.created_at, otherPerson.created_at)

        const mergeAllowed = this.isMergeAllowed(otherPerson)

        this.statsd?.increment('merge_users', {
            call: shouldIdentifyPerson ? 'identify' : 'alias',
            teamId: this.teamId.toString(),
            oldPersonIdentified: String(otherPerson.is_identified),
            newPersonIdentified: String(mergeInto.is_identified),
            // For analyzing impact of merges we need to know how old data would need to get updated
            // If we are smart we merge the newer person into the older one,
            // so we need to know the newer person's age
            newerPersonAgeInMonths: String(ageInMonthsLowCardinality(newerCreatedAt)),
        })

        // If merge isn't allowed, we will ignore it, log an ingestion warning and exit
        if (!mergeAllowed) {
            // TODO: add event UUID to the ingestion warning
            captureIngestionWarning(this.db, this.teamId, 'cannot_merge_already_identified', {
                sourcePersonDistinctId: otherPersonDistinctId,
                targetPersonDistinctId: mergeIntoDistinctId,
            })
            status.warn('🤔', 'refused to merge an already identified user via an $identify or $create_alias call')
            return
        }

        // How the merge works:
        // Merging properties:
        //   on key conflict we use the properties from the person provided as the first argument in identify or alias calls (mergeInto person),
        //   Note it's important for us to compute this before potentially swapping the persons for personID merging purposes in PoEEmbraceJoin mode
        // In case of PoE Embrace the join mode:
        //   we want to keep using the older person to reduce the number of partitions that need to be updated during squash
        //   to do that we'll swap otherPerson and mergeInto person (after properties merge computation!)
        //   additionally update person overrides table in postgres and clickhouse
        //   TODO: ^
        // If the merge fails:
        //   we'll roll back the transaction and then try from scratch in the origial order of persons provided for property merges
        //   that guarantees consistency of how properties are processed regardless of persons created_at timestamps and rollout state
        //   we're calling aliasDeprecated as we need to refresh the persons info completely first

        let properties: Properties = { ...otherPerson.properties, ...mergeInto.properties }
        properties = this.applyEventPropertyUpdates(properties)

        if (this.poEEmbraceJoin) {
            // Optimize merging persons to keep using the person id that has longer history,
            // which means we'll have less events to update during the squash later
            if (otherPerson.created_at < mergeInto.created_at) {
                ;[mergeInto, otherPerson] = [otherPerson, mergeInto]
            }
        }

        const [kafkaMessages, mergedPerson] = await this.handleMergeTransaction(
            mergeInto,
            otherPerson,
            olderCreatedAt, // Keep the oldest created_at (i.e. the first time we've seen either person)
            properties
        )
        await this.db.kafkaProducer.queueMessages(kafkaMessages)

        // :KLUDGE: Avoid unneeded fetches in updateProperties()
        this.personContainer = this.personContainer.with(mergedPerson)
    }

    private isMergeAllowed(mergeFrom: Person): boolean {
        // $create_alias and $identify will not merge a user who's already identified into anyone else
        return !mergeFrom.is_identified
    }

    private async handleMergeTransaction(
        mergeInto: Person,
        otherPerson: Person,
        createdAt: DateTime,
        properties: Properties
    ): Promise<[ProducerRecord[], Person]> {
        return await this.db.postgresTransaction('mergePeople', async (client) => {
            const [person, updatePersonMessages] = await this.db.updatePersonDeprecated(
                mergeInto,
                {
                    created_at: createdAt,
                    properties: properties,
                    is_identified: true,
                },
                client
            )

            // Merge the distinct IDs
            // TODO: Doesn't this table need to add updates to CH too?
            await this.handleTablesDependingOnPersonID(otherPerson, mergeInto, client)

            const distinctIdMessages = await this.db.moveDistinctIds(otherPerson, mergeInto, client)

            const deletePersonMessages = await this.db.deletePerson(otherPerson, client)

            let personOverrideMessages: ProducerRecord[] = []
            if (this.poEEmbraceJoin) {
                personOverrideMessages = [await this.addPersonOverride(otherPerson, mergeInto, client)]
            }

            return [
                [...personOverrideMessages, ...updatePersonMessages, ...distinctIdMessages, ...deletePersonMessages],
                person,
            ]
        })
    }

    private async addPersonOverride(
        oldPerson: Person,
        overridePerson: Person,
        client?: PoolClient
    ): Promise<ProducerRecord> {
        const mergedAt = DateTime.now()
        const oldestEvent = overridePerson.created_at
        /**
            We'll need to do two updates:

         1. to add an override from oldPerson to override person
         2. update any entries that have oldPerson as the override person to now also point to the new override person

            TODO: how do we want to be updating oldest_event?

         I'm thinking: we write it if it's not there, but don't update it on conflicts (alternative update to the older date)
         In the transitive one the same don't update or update to older data (if that's not too complex to do)
         it's an optimization anyway and squash job might be updating those values anyway and it's just a hint, so ignoring if complex seems better
         in any case it's important that we use the oldest_event we stored in postgres in CH too.
        */

        const {
            rows: [{ version }],
        } = await this.db.postgresQuery(
            SQL`
                INSERT INTO posthog_personoverride (
                    team_id, 
                    old_person_id, 
                    override_person_id, 
                    oldest_event,
                    version
                ) VALUES (
                    ${this.teamId}, 
                    ${oldPerson.uuid}, 
                    ${overridePerson.uuid}, 
                    ${oldestEvent}, 
                    1
                )
                RETURNING version;
            `,
            undefined,
            'personOverride',
            client
        )

        const { rows: transitiveUpdates } = await this.db.postgresQuery(
            SQL`
                UPDATE 
                    posthog_personoverride
                SET 
                    override_person_id = ${overridePerson.uuid}, version = version + 1
                WHERE
                    team_id = ${this.teamId} AND override_person_id = ${oldPerson.uuid}
                RETURNING
                    old_person_id,
                    version,
                    oldest_event;
            `,
            undefined,
            'transitivePersonOverrides',
            client
        )

        status.debug('🔁', 'person_overrides_updated', { transitiveUpdates })

        const personOverrideMessages: ProducerRecord = {
            topic: KAFKA_PERSON_OVERRIDE,
            messages: [
                {
                    value: JSON.stringify({
                        team_id: oldPerson.team_id,
                        merged_at: mergedAt,
                        override_person_id: overridePerson.id,
                        old_person_id: oldPerson.id,
                        oldest_event: oldestEvent,
                        version: version,
                    }),
                },
                ...transitiveUpdates.map(({ oldPersonId, version, oldestEvent }) => ({
                    value: JSON.stringify({
                        team_id: oldPerson.team_id,
                        merged_at: mergedAt,
                        override_person_id: overridePerson.id,
                        old_person_id: oldPersonId,
                        oldest_event: oldestEvent,
                        version: version,
                    }),
                })),
            ],
        }
        return personOverrideMessages
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
export function updatePersonState(...params: ConstructorParameters<typeof PersonState>): Promise<LazyPersonContainer> {
    return new PersonState(...params).update()
}

export function ageInMonthsLowCardinality(timestamp: DateTime): number {
    const ageInMonths = Math.max(-Math.floor(timestamp.diffNow('months').months), 0)
    // for getting low cardinality for statsd metrics tags, which can cause issues in e.g. InfluxDB: https://docs.influxdata.com/influxdb/cloud/write-data/best-practices/resolve-high-cardinality/
    const ageLowCardinality = Math.min(ageInMonths, 50)
    return ageLowCardinality
}

function SQL(sqlParts: TemplateStringsArray, ...args: any[]): { text: string; values: any[] } {
    // Generates a node-pq compatible query object given a tagged
    // template literal. The intention is to remove the need to match up
    // the positional arguments with the $1, $2, etc. placeholders in
    // the query string.
    const text = sqlParts.reduce((acc, part, i) => acc + '$' + i + part)
    const values = args
    return { text, values }
}

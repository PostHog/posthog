import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import equal from 'fast-deep-equal'
import { StatsD } from 'hot-shots'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { PoolClient } from 'pg'

import { KAFKA_PERSON_OVERRIDE } from '../../config/kafka-topics'
import { Person, PropertyUpdateOperation, TimestampFormat } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { castTimestampOrNow, NoRowsUpdatedError, UUIDT } from '../../utils/utils'
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
    maxMergeAttempts: number

    private db: DB
    private statsd: StatsD | undefined
    private personManager: PersonManager
    public updateIsIdentified: boolean // TODO: remove this from the class and being hidden
    private poEEmbraceJoin: boolean

    constructor(
        event: PluginEvent,
        teamId: number,
        distinctId: string,
        timestamp: DateTime,
        db: DB,
        statsd: StatsD | undefined,
        personManager: PersonManager,
        poEEmbraceJoin: boolean,
        uuid: UUIDT | undefined = undefined,
        maxMergeAttempts: number = MAX_FAILED_PERSON_MERGE_ATTEMPTS
    ) {
        this.event = event
        this.distinctId = distinctId
        this.teamId = teamId
        this.eventProperties = event.properties!
        this.timestamp = timestamp
        this.newUuid = (uuid || new UUIDT()).toString()
        this.maxMergeAttempts = maxMergeAttempts

        this.db = db
        this.statsd = statsd
        this.personManager = personManager

        // If set to true, we'll update `is_identified` at the end of `updateProperties`
        // :KLUDGE: This is an indirect communication channel between `handleIdentifyOrAlias` and `updateProperties`
        this.updateIsIdentified = false

        // For persons on events embrace the join gradual roll-out, remove after fully rolled out
        this.poEEmbraceJoin = poEEmbraceJoin
    }

    async update(): Promise<Person> {
        const person: Person | undefined = await this.handleIdentifyOrAlias() // TODO: make it also return a boolean for if we can exit early here
        return await this.updateProperties(person)
    }

    async updateProperties(person?: Person): Promise<Person> {
        if (!person) {
            let personCreated: boolean
            ;[person, personCreated] = await this.createOrGetPerson()
            if (personCreated) {
                // In this case we already set all the properties during creation so we can exit
                return person
            }
        }
        // At this point this.person is guaranteed to be defined
        if (
            this.eventProperties['$set'] ||
            this.eventProperties['$set_once'] ||
            this.eventProperties['$unset'] ||
            this.updateIsIdentified
        ) {
            person = await this.updatePersonProperties(person)
        }
        return person
    }

    private async createOrGetPerson(): Promise<[Person, boolean]> {
        // returns: Person, if person was created
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
                return [person, true]
            } catch (error) {
                status.error('🚨', 'create_person_failed', { error, teamId: this.teamId, distinctId: this.distinctId })
                if (!error.message || !error.message.includes('duplicate key value violates unique constraint')) {
                    Sentry.captureException(error, {
                        tags: { team_id: this.teamId },
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

        return [await this.getPersonOrError(), false]
    }

    private async getPersonOrError(): Promise<Person> {
        const person = await this.db.fetchPerson(this.teamId, this.distinctId)
        if (!person) {
            // There are three options for how we got here:
            // - person creation is ongoing (but we're currently not parallel processing ingestion for the same ID)
            // - person creation failed (rare)
            // - person was deleted (rare)
            // TODO: retries for creation and/or fetching
            const error = Error('Race condition: Person has been deleted or creation failed')
            status.error('🚨', 'get_person_failed', { error, teamId: this.teamId, distinctId: this.distinctId })
            Sentry.captureException(error, {
                extra: {
                    teamId: this.teamId,
                    distinctId: this.distinctId,
                    timestamp: this.timestamp,
                    personUuid: this.newUuid,
                },
            })
            throw error
        }
        return person
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

    private async updatePersonProperties(person: Person): Promise<Person> {
        try {
            return await this.tryUpdatePerson(person)
        } catch (error) {
            // The person might have been merged between start of processing and now
            // Retry with the person fetched from the DB
            // TODO: multiple retries like merges, we might need to create a person if they were deleted in the past
            if (error instanceof NoRowsUpdatedError) {
                return await this.tryUpdatePerson(await this.getPersonOrError())
            } else {
                throw error
            }
        }
    }

    private async tryUpdatePerson(person: Person): Promise<Person> {
        const update: Partial<Person> = {}
        const updatedProperties = this.applyEventPropertyUpdates(person.properties || {})

        if (!equal(person.properties, updatedProperties)) {
            update.properties = updatedProperties
        }
        if (this.updateIsIdentified && !person.is_identified) {
            update.is_identified = true
        }

        if (Object.keys(update).length > 0) {
            // Note: we're not passing the client, so kafka messages are waited for within the function
            ;[person] = await this.db.updatePersonDeprecated(person, update)
        }
        return person
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

    async handleIdentifyOrAlias(): Promise<Person | undefined> {
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
            if (['$create_alias', '$merge_dangerously'].includes(this.event.event) && this.eventProperties['alias']) {
                return await this.merge(
                    String(this.eventProperties['alias']),
                    this.distinctId,
                    this.teamId,
                    this.timestamp
                )
            } else if (this.event.event === '$identify' && this.eventProperties['$anon_distinct_id']) {
                return await this.merge(
                    String(this.eventProperties['$anon_distinct_id']),
                    this.distinctId,
                    this.teamId,
                    this.timestamp
                )
            }
        } catch (e) {
            // TODO: should we throw
            console.error('handleIdentifyOrAlias failed', e, this.event)
        } finally {
            clearTimeout(timeout)
        }
        return undefined
    }

    public async merge(
        otherPersonDistinctId: string,
        mergeIntoDistinctId: string,
        teamId: number,
        timestamp: DateTime
    ): Promise<Person | undefined> {
        // No reason to alias person against itself. Done by posthog-node when updating user properties
        if (mergeIntoDistinctId === otherPersonDistinctId) {
            return undefined
        }
        if (isDistinctIdIllegal(mergeIntoDistinctId)) {
            this.statsd?.increment('illegal_distinct_ids.total', { distinctId: mergeIntoDistinctId })
            captureIngestionWarning(this.db, teamId, 'cannot_merge_with_illegal_distinct_id', {
                illegalDistinctId: mergeIntoDistinctId,
                otherDistinctId: otherPersonDistinctId,
                eventUuid: this.event.uuid,
            })
            return undefined
        }
        if (isDistinctIdIllegal(otherPersonDistinctId)) {
            this.statsd?.increment('illegal_distinct_ids.total', { distinctId: otherPersonDistinctId })
            captureIngestionWarning(this.db, teamId, 'cannot_merge_with_illegal_distinct_id', {
                illegalDistinctId: otherPersonDistinctId,
                otherDistinctId: mergeIntoDistinctId,
                eventUuid: this.event.uuid,
            })
            return undefined
        }
        return await this.mergeWithoutValidation(otherPersonDistinctId, mergeIntoDistinctId, teamId, timestamp, 0)
    }

    private async mergeWithoutValidation(
        otherPersonDistinctId: string,
        mergeIntoDistinctId: string,
        teamId: number,
        timestamp: DateTime,
        totalMergeAttempts = 0
    ): Promise<Person> {
        this.updateIsIdentified = true

        const otherPerson = await this.db.fetchPerson(teamId, otherPersonDistinctId)
        const mergeIntoPerson = await this.db.fetchPerson(teamId, mergeIntoDistinctId)

        try {
            if (otherPerson && !mergeIntoPerson) {
                await this.db.addDistinctId(otherPerson, mergeIntoDistinctId)
                return otherPerson
            } else if (!otherPerson && mergeIntoPerson) {
                await this.db.addDistinctId(mergeIntoPerson, otherPersonDistinctId)
                return mergeIntoPerson
            } else if (otherPerson && mergeIntoPerson) {
                if (otherPerson.id == mergeIntoPerson.id) {
                    return mergeIntoPerson
                }
                return await this.mergePeople({
                    mergeInto: mergeIntoPerson,
                    mergeIntoDistinctId: mergeIntoDistinctId,
                    otherPerson: otherPerson,
                    otherPersonDistinctId: otherPersonDistinctId,
                })
            }
            //  The last case: (!oldPerson && !newPerson)
            return await this.createPerson(
                // TODO: in this case we could skip the properties updates later
                timestamp,
                this.eventProperties['$set'] || {},
                this.eventProperties['$set_once'] || {},
                teamId,
                null,
                true,
                this.newUuid,
                this.event.uuid,
                [mergeIntoDistinctId, otherPersonDistinctId]
            )
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
            status.error('🚨', 'merge_failed', {
                error,
                teamId: this.teamId,
                previousDistinctId: otherPersonDistinctId,
                distinctId: mergeIntoDistinctId,
            })
            totalMergeAttempts++
            if (totalMergeAttempts >= this.maxMergeAttempts) {
                status.error('🚨', 'merge_failed_final', {
                    error,
                    teamId: this.teamId,
                    previousDistinctId: otherPersonDistinctId,
                    distinctId: mergeIntoDistinctId,
                })
                throw error // Very much not OK, failed repeatedly so rethrowing the error
            }
            return await this.mergeWithoutValidation(
                otherPersonDistinctId,
                mergeIntoDistinctId,
                teamId,
                timestamp,
                totalMergeAttempts
            )
        }
    }

    public async mergePeople({
        mergeInto,
        mergeIntoDistinctId,
        otherPerson,
        otherPersonDistinctId,
    }: {
        mergeInto: Person
        mergeIntoDistinctId: string
        otherPerson: Person
        otherPersonDistinctId: string
    }): Promise<Person> {
        const olderCreatedAt = DateTime.min(mergeInto.created_at, otherPerson.created_at)
        const newerCreatedAt = DateTime.max(mergeInto.created_at, otherPerson.created_at)

        const mergeAllowed = this.isMergeAllowed(otherPerson)

        this.statsd?.increment('merge_users', {
            call: this.event.event, // $identify, $create_alias or $merge_dangerously
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
                eventUuid: this.event.uuid,
            })
            status.warn('🤔', 'refused to merge an already identified user via an $identify or $create_alias call')
            return mergeInto // We're returning the original person tied to distinct_id used for the event
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
        return mergedPerson
    }

    private isMergeAllowed(mergeFrom: Person): boolean {
        // $merge_dangerously has no restrictions
        // $create_alias and $identify will not merge a user who's already identified into anyone else
        return this.event.event === '$merge_dangerously' || !mergeFrom.is_identified
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
            We'll need to do 4 updates:

         1. Add the persons involved to the helper table (2 of them)
         2. Add an override from oldPerson to override person
         3. Update any entries that have oldPerson as the override person to now also point to the new override person. Note that we don't update `oldest_event`, because it's a heuristic (used to optimise squashing) tied to the old_person and nothing changed about the old_person who's events need to get squashed.
         */
        const oldPersonId = await this.addPersonOverrideMapping(oldPerson, client)
        const overridePersonId = await this.addPersonOverrideMapping(overridePerson, client)

        await this.db.postgresQuery(
            SQL`
                INSERT INTO posthog_personoverride (
                    team_id,
                    old_person_id,
                    override_person_id,
                    oldest_event,
                    version
                ) VALUES (
                    ${this.teamId},
                    ${oldPersonId},
                    ${overridePersonId},
                    ${oldestEvent},
                    0
                )
            `,
            undefined,
            'personOverride',
            client
        )

        // The follow-up JOIN is required as ClickHouse requires UUIDs, so we need to fetch the UUIDs
        // of the IDs we updated from the mapping table.
        const { rows: transitiveUpdates } = await this.db.postgresQuery(
            SQL`
                WITH updated_ids AS (
                    UPDATE
                        posthog_personoverride
                    SET
                        override_person_id = ${overridePersonId}, version = COALESCE(version, 0)::numeric + 1
                    WHERE
                        team_id = ${this.teamId} AND override_person_id = ${oldPersonId}
                    RETURNING
                        old_person_id,
                        version,
                        oldest_event
                )
                SELECT
                    helper.uuid as old_person_id,
                    updated_ids.version,
                    updated_ids.oldest_event
                FROM
                    updated_ids
                JOIN
                    posthog_personoverridemapping helper
                ON
                    helper.id = updated_ids.old_person_id;
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
                        merged_at: castTimestampOrNow(mergedAt, TimestampFormat.ClickHouse),
                        override_person_id: overridePerson.uuid,
                        old_person_id: oldPerson.uuid,
                        oldest_event: castTimestampOrNow(oldestEvent, TimestampFormat.ClickHouse),
                        version: 0,
                    }),
                },
                ...transitiveUpdates.map(({ old_person_id, version, oldest_event }) => ({
                    value: JSON.stringify({
                        team_id: oldPerson.team_id,
                        merged_at: castTimestampOrNow(mergedAt, TimestampFormat.ClickHouse),
                        override_person_id: overridePerson.uuid,
                        old_person_id: old_person_id,
                        oldest_event: castTimestampOrNow(oldest_event, TimestampFormat.ClickHouse),
                        version: version,
                    }),
                })),
            ],
        }

        return personOverrideMessages
    }

    private async addPersonOverrideMapping(person: Person, client?: PoolClient): Promise<number> {
        /**
            Update the helper table that serves as a mapping between a serial ID and a Person UUID.

            This mapping is used to enable an exclusion constraint in the personoverrides table, which
            requires int[], while avoiding any constraints on "hotter" tables, like person.
         **/

        // ON CONFLICT nothing is returned, so we get the id in the second SELECT statement below.
        // Fear not, the constraints on personoverride will handle any inconsistencies.
        // This mapping table is really nothing more than a mapping to support exclusion constraints
        // as we map int ids to UUIDs (the latter not supported in exclusion contraints).
        const {
            rows: [{ id }],
        } = await this.db.postgresQuery(
            `WITH insert_id AS (
                    INSERT INTO posthog_personoverridemapping(
                        team_id,
                        uuid
                    )
                    VALUES (
                        ${this.teamId},
                        '${person.uuid}'
                    )
                    ON CONFLICT("team_id", "uuid") DO NOTHING
                    RETURNING id
                )
                SELECT * FROM insert_id
                UNION ALL
                SELECT id
                FROM posthog_personoverridemapping
                WHERE uuid = '${person.uuid}'
            `,
            undefined,
            'personOverrideMapping',
            client
        )

        return id
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

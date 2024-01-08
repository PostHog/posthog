import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { Counter } from 'prom-client'
import { KafkaProducerWrapper } from 'utils/db/kafka-producer-wrapper'

import { KAFKA_PERSON_OVERRIDE } from '../../config/kafka-topics'
import { Person, PropertyUpdateOperation, TimestampFormat } from '../../types'
import { DB } from '../../utils/db/db'
import { PostgresRouter, PostgresUse, TransactionClient } from '../../utils/db/postgres'
import { timeoutGuard } from '../../utils/db/utils'
import { PeriodicTask } from '../../utils/periodic-task'
import { promiseRetry } from '../../utils/retries'
import { status } from '../../utils/status'
import { castTimestampOrNow, UUIDT } from '../../utils/utils'
import { captureIngestionWarning } from './utils'

const MAX_FAILED_PERSON_MERGE_ATTEMPTS = 3

export const mergeFinalFailuresCounter = new Counter({
    name: 'person_merge_final_failure_total',
    help: 'Number of person merge final failures.',
})

export const mergeTxnAttemptCounter = new Counter({
    name: 'person_merge_txn_attempt_total',
    help: 'Number of person merge attempts.',
    labelNames: ['call', 'oldPersonIdentified', 'newPersonIdentified', 'poEEmbraceJoin'],
})

export const mergeTxnSuccessCounter = new Counter({
    name: 'person_merge_txn_success_total',
    help: 'Number of person merges that succeeded.',
    labelNames: ['call', 'oldPersonIdentified', 'newPersonIdentified', 'poEEmbraceJoin'],
})

// used to prevent identify from being used with generic IDs
// that we can safely assume stem from a bug or mistake
// used to prevent identify from being used with generic IDs
// that we can safely assume stem from a bug or mistake
const BARE_CASE_INSENSITIVE_ILLEGAL_IDS = [
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
]

const BARE_CASE_SENSITIVE_ILLEGAL_IDS = ['[object Object]', 'NaN', 'None', 'none', 'null', '0', 'undefined']

// we have seen illegal ids received but wrapped in double quotes
// to protect ourselves from this we'll add the single- and double-quoted versions of the illegal ids
const singleQuoteIds = (ids: string[]) => ids.map((id) => `'${id}'`)
const doubleQuoteIds = (ids: string[]) => ids.map((id) => `"${id}"`)

// some ids are illegal regardless of casing
// while others are illegal only when cased
// so, for example, we want to forbid `NaN` but not `nan`
// but, we will forbid `uNdEfInEd` and `undefined`
const CASE_INSENSITIVE_ILLEGAL_IDS = new Set(
    BARE_CASE_INSENSITIVE_ILLEGAL_IDS.concat(singleQuoteIds(BARE_CASE_INSENSITIVE_ILLEGAL_IDS)).concat(
        doubleQuoteIds(BARE_CASE_INSENSITIVE_ILLEGAL_IDS)
    )
)

const CASE_SENSITIVE_ILLEGAL_IDS = new Set(
    BARE_CASE_SENSITIVE_ILLEGAL_IDS.concat(singleQuoteIds(BARE_CASE_SENSITIVE_ILLEGAL_IDS)).concat(
        doubleQuoteIds(BARE_CASE_SENSITIVE_ILLEGAL_IDS)
    )
)

const isDistinctIdIllegal = (id: string): boolean => {
    const trimmed = id.trim()
    return trimmed === '' || CASE_INSENSITIVE_ILLEGAL_IDS.has(id.toLowerCase()) || CASE_SENSITIVE_ILLEGAL_IDS.has(id)
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
    public updateIsIdentified: boolean // TODO: remove this from the class and being hidden

    constructor(
        event: PluginEvent,
        teamId: number,
        distinctId: string,
        timestamp: DateTime,
        db: DB,
        private personOverrideWriter?: DeferredPersonOverrideWriter,
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

        // If set to true, we'll update `is_identified` at the end of `updateProperties`
        // :KLUDGE: This is an indirect communication channel between `handleIdentifyOrAlias` and `updateProperties`
        this.updateIsIdentified = false
    }

    async update(): Promise<Person> {
        const person: Person | undefined = await this.handleIdentifyOrAlias() // TODO: make it also return a boolean for if we can exit early here
        if (person) {
            // try to shortcut if we have the person from identify or alias
            try {
                return await this.updatePersonProperties(person)
            } catch (error) {
                // shortcut didn't work, swallow the error and try normal retry loop below
                status.debug('🔁', `failed update after adding distinct IDs, retrying`, { error })
            }
        }
        return await this.handleUpdate()
    }

    async handleUpdate(): Promise<Person> {
        // There are various reasons why update can fail:
        // - anothe thread created the person during a race
        // - the person might have been merged between start of processing and now
        // we simply and stupidly start from scratch
        return await promiseRetry(() => this.updateProperties(), 'update_person')
    }

    async updateProperties(): Promise<Person> {
        const [person, propertiesHandled] = await this.createOrGetPerson()
        if (propertiesHandled) {
            return person
        }
        return await this.updatePersonProperties(person)
    }

    /**
     * @returns [Person, boolean that indicates if properties were already handled or not]
     */
    private async createOrGetPerson(): Promise<[Person, boolean]> {
        let person = await this.db.fetchPerson(this.teamId, this.distinctId)
        if (person) {
            return [person, false]
        }

        const properties = this.eventProperties['$set'] || {}
        const propertiesOnce = this.eventProperties['$set_once'] || {}
        person = await this.createPerson(
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
        person.properties ||= {}

        const update: Partial<Person> = {}
        if (this.applyEventPropertyUpdates(person.properties)) {
            update.properties = person.properties
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

    /**
     * @param personProperties Properties of the person to be updated, these are updated in place.
     * @returns true if the properties were changed, false if they were not
     */
    private applyEventPropertyUpdates(personProperties: Properties): boolean {
        const properties: Properties = this.eventProperties['$set'] || {}
        const propertiesOnce: Properties = this.eventProperties['$set_once'] || {}
        const unsetProps = this.eventProperties['$unset']
        const unsetProperties: Array<string> = Array.isArray(unsetProps)
            ? unsetProps
            : Object.keys(unsetProps || {}) || []

        let updated = false
        Object.entries(propertiesOnce).map(([key, value]) => {
            if (typeof personProperties[key] === 'undefined') {
                updated = true
                personProperties[key] = value
            }
        })
        Object.entries(properties).map(([key, value]) => {
            if (personProperties[key] !== value) {
                updated = true
                personProperties[key] = value
            }
        })
        unsetProperties.forEach((propertyKey) => {
            if (propertyKey in personProperties) {
                updated = true
                delete personProperties[propertyKey]
            }
        })

        return updated
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
            } else if (this.event.event === '$identify' && '$anon_distinct_id' in this.eventProperties) {
                return await this.merge(
                    String(this.eventProperties['$anon_distinct_id']),
                    this.distinctId,
                    this.teamId,
                    this.timestamp
                )
            }
        } catch (e) {
            Sentry.captureException(e, {
                tags: { team_id: this.teamId, pipeline_step: 'processPersonsStep' },
                extra: {
                    location: 'handleIdentifyOrAlias',
                    distinctId: this.distinctId,
                    anonId: String(this.eventProperties['$anon_distinct_id']),
                    alias: String(this.eventProperties['alias']),
                },
            })
            mergeFinalFailuresCounter.inc()
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
            await captureIngestionWarning(this.db, teamId, 'cannot_merge_with_illegal_distinct_id', {
                illegalDistinctId: mergeIntoDistinctId,
                otherDistinctId: otherPersonDistinctId,
                eventUuid: this.event.uuid,
            })
            return undefined
        }
        if (isDistinctIdIllegal(otherPersonDistinctId)) {
            await captureIngestionWarning(this.db, teamId, 'cannot_merge_with_illegal_distinct_id', {
                illegalDistinctId: otherPersonDistinctId,
                otherDistinctId: mergeIntoDistinctId,
                eventUuid: this.event.uuid,
            })
            return undefined
        }
        return promiseRetry(
            () => this.mergeDistinctIds(otherPersonDistinctId, mergeIntoDistinctId, teamId, timestamp),
            'merge_distinct_ids'
        )
    }

    private async mergeDistinctIds(
        otherPersonDistinctId: string,
        mergeIntoDistinctId: string,
        teamId: number,
        timestamp: DateTime
    ): Promise<Person> {
        this.updateIsIdentified = true

        const otherPerson = await this.db.fetchPerson(teamId, otherPersonDistinctId)
        const mergeIntoPerson = await this.db.fetchPerson(teamId, mergeIntoDistinctId)

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
        const mergeAllowed = this.isMergeAllowed(otherPerson)

        // If merge isn't allowed, we will ignore it, log an ingestion warning and exit
        if (!mergeAllowed) {
            // TODO: add event UUID to the ingestion warning
            await captureIngestionWarning(this.db, this.teamId, 'cannot_merge_already_identified', {
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

        const properties: Properties = { ...otherPerson.properties, ...mergeInto.properties }
        this.applyEventPropertyUpdates(properties)

        if (this.personOverrideWriter) {
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
        mergeTxnAttemptCounter
            .labels({
                call: this.event.event, // $identify, $create_alias or $merge_dangerously
                oldPersonIdentified: String(otherPerson.is_identified),
                newPersonIdentified: String(mergeInto.is_identified),
                poEEmbraceJoin: String(!!this.personOverrideWriter),
            })
            .inc()

        const result: [ProducerRecord[], Person] = await this.db.postgres.transaction(
            PostgresUse.COMMON_WRITE,
            'mergePeople',
            async (tx) => {
                const [person, updatePersonMessages] = await this.db.updatePersonDeprecated(
                    mergeInto,
                    {
                        created_at: createdAt,
                        properties: properties,
                        is_identified: true,
                    },
                    tx
                )

                // Merge the distinct IDs
                // TODO: Doesn't this table need to add updates to CH too?
                await this.db.updateCohortsAndFeatureFlagsForMerge(
                    otherPerson.team_id,
                    otherPerson.id,
                    mergeInto.id,
                    tx
                )

                const distinctIdMessages = await this.db.moveDistinctIds(otherPerson, mergeInto, tx)

                const deletePersonMessages = await this.db.deletePerson(otherPerson, tx)

                if (this.personOverrideWriter) {
                    await this.personOverrideWriter.addPersonOverride(
                        tx,
                        getPersonOverrideDetails(this.teamId, otherPerson, mergeInto)
                    )
                }

                return [[...updatePersonMessages, ...distinctIdMessages, ...deletePersonMessages], person]
            }
        )

        mergeTxnSuccessCounter
            .labels({
                call: this.event.event, // $identify, $create_alias or $merge_dangerously
                oldPersonIdentified: String(otherPerson.is_identified),
                newPersonIdentified: String(mergeInto.is_identified),
                poEEmbraceJoin: String(!!this.personOverrideWriter),
            })
            .inc()
        return result
    }
}

/**
 * A record of a merge operation occurring.
 *
 * These property names need to be kept in sync with the ``PersonOverride``
 * Django model (and ``posthog_personoverride`` table schema) as defined in
 * ``posthog/models/person/person.py``.
 */
type PersonOverrideDetails = {
    team_id: number
    old_person_id: string
    override_person_id: string
    oldest_event: DateTime
}

function getPersonOverrideDetails(teamId: number, oldPerson: Person, overridePerson: Person): PersonOverrideDetails {
    if (teamId != oldPerson.team_id || teamId != overridePerson.team_id) {
        throw new Error('cannot merge persons across different teams')
    }
    return {
        team_id: teamId,
        old_person_id: oldPerson.uuid,
        override_person_id: overridePerson.uuid,
        oldest_event: overridePerson.created_at,
    }
}

export class FlatPersonOverrideWriter {
    constructor(private postgres: PostgresRouter) {}

    public async addPersonOverride(
        tx: TransactionClient,
        overrideDetails: PersonOverrideDetails
    ): Promise<ProducerRecord[]> {
        const mergedAt = DateTime.now()

        await this.postgres.query(
            tx,
            SQL`
                INSERT INTO posthog_flatpersonoverride (
                    team_id,
                    old_person_id,
                    override_person_id,
                    oldest_event,
                    version
                ) VALUES (
                    ${overrideDetails.team_id},
                    ${overrideDetails.old_person_id},
                    ${overrideDetails.override_person_id},
                    ${overrideDetails.oldest_event},
                    0
                )
            `,
            undefined,
            'personOverride'
        )

        const { rows: transitiveUpdates } = await this.postgres.query(
            tx,
            SQL`
                UPDATE
                    posthog_flatpersonoverride
                SET
                    override_person_id = ${overrideDetails.override_person_id},
                    version = COALESCE(version, 0)::numeric + 1
                WHERE
                    team_id = ${overrideDetails.team_id} AND override_person_id = ${overrideDetails.old_person_id}
                RETURNING
                    old_person_id,
                    version,
                    oldest_event
            `,
            undefined,
            'transitivePersonOverrides'
        )

        status.debug('🔁', 'person_overrides_updated', { transitiveUpdates })

        const personOverrideMessages: ProducerRecord[] = [
            {
                topic: KAFKA_PERSON_OVERRIDE,
                messages: [
                    {
                        value: JSON.stringify({
                            team_id: overrideDetails.team_id,
                            old_person_id: overrideDetails.old_person_id,
                            override_person_id: overrideDetails.override_person_id,
                            oldest_event: castTimestampOrNow(overrideDetails.oldest_event, TimestampFormat.ClickHouse),
                            merged_at: castTimestampOrNow(mergedAt, TimestampFormat.ClickHouse),
                            version: 0,
                        }),
                    },
                    ...transitiveUpdates.map(({ old_person_id, version, oldest_event }) => ({
                        value: JSON.stringify({
                            team_id: overrideDetails.team_id,
                            old_person_id: old_person_id,
                            override_person_id: overrideDetails.override_person_id,
                            oldest_event: castTimestampOrNow(oldest_event, TimestampFormat.ClickHouse),
                            merged_at: castTimestampOrNow(mergedAt, TimestampFormat.ClickHouse),
                            version: version,
                        }),
                    })),
                ],
            },
        ]

        return personOverrideMessages
    }

    public async getPersonOverrides(teamId: number): Promise<PersonOverrideDetails[]> {
        const { rows } = await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            SQL`
                SELECT
                    team_id,
                    old_person_id,
                    override_person_id,
                    oldest_event
                FROM posthog_flatpersonoverride
                WHERE team_id = ${teamId}
            `,
            undefined,
            'getPersonOverrides'
        )
        return rows.map((row) => ({
            ...row,
            team_id: parseInt(row.team_id), // XXX: pg returns bigint as str (reasonably so)
            oldest_event: DateTime.fromISO(row.oldest_event),
        }))
    }
}

const deferredPersonOverridesWrittenCounter = new Counter({
    name: 'deferred_person_overrides_written',
    help: 'Number of person overrides that have been written as pending',
})
export class DeferredPersonOverrideWriter {
    constructor(private postgres: PostgresRouter) {}

    /**
     * Enqueue an override for deferred processing.
     */
    public async addPersonOverride(tx: TransactionClient, overrideDetails: PersonOverrideDetails): Promise<void> {
        await this.postgres.query(
            tx,
            SQL`
            INSERT INTO posthog_pendingpersonoverride (
                team_id,
                old_person_id,
                override_person_id,
                oldest_event
            ) VALUES (
                ${overrideDetails.team_id},
                ${overrideDetails.old_person_id},
                ${overrideDetails.override_person_id},
                ${overrideDetails.oldest_event}
            )`,
            undefined,
            'pendingPersonOverride'
        )
        deferredPersonOverridesWrittenCounter.inc()
    }
}

const deferredPersonOverridesProcessedCounter = new Counter({
    name: 'deferred_person_overrides_processed',
    help: 'Number of pending person overrides that have been successfully processed',
})

export class DeferredPersonOverrideWorker {
    // This lock ID is used as an advisory lock identifier/key for a lock that
    // ensures only one worker is able to update the overrides table at a time.
    // (We do this to make it simpler to ensure that we maintain the consistency
    // of transitive updates.) There isn't any special significance to this
    // particular value (other than Postgres requires it to be a numeric one),
    // it just needs to be consistent across all processes.
    public readonly lockId = 567

    constructor(
        private postgres: PostgresRouter,
        private kafkaProducer: KafkaProducerWrapper,
        private writer: FlatPersonOverrideWriter
    ) {}

    /**
     * Process all (or up to the given limit) pending overrides.
     *
     * An advisory lock is acquired prior to processing to ensure that this
     * function has exclusive access to the pending overrides during the update
     * process.
     *
     * @returns the number of overrides processed
     */
    public async processPendingOverrides(limit?: number): Promise<number> {
        const overridesCount = await this.postgres.transaction(
            PostgresUse.COMMON_WRITE,
            'processPendingOverrides',
            async (tx) => {
                const {
                    rows: [{ acquired }],
                } = await this.postgres.query(
                    tx,
                    SQL`SELECT pg_try_advisory_xact_lock(${this.lockId}) as acquired`,
                    undefined,
                    'processPendingOverrides'
                )
                if (!acquired) {
                    throw new Error('could not acquire lock')
                }

                // n.b.: Ordering by id ensures we are processing in (roughly) FIFO order
                const { rows } = await this.postgres.query(
                    tx,
                    `SELECT * FROM posthog_pendingpersonoverride ORDER BY id` +
                        (limit !== undefined ? ` LIMIT ${limit}` : ''),
                    undefined,
                    'processPendingOverrides'
                )

                const messages: ProducerRecord[] = []
                for (const { id, ...mergeOperation } of rows) {
                    messages.push(...(await this.writer.addPersonOverride(tx, mergeOperation)))
                    await this.postgres.query(
                        tx,
                        SQL`DELETE FROM posthog_pendingpersonoverride WHERE id = ${id}`,
                        undefined,
                        'processPendingOverrides'
                    )
                }

                // n.b.: We publish the messages here (and wait for acks) to ensure
                // that all of our override updates are sent to Kafka prior to
                // committing the transaction. If we're unable to publish, we should
                // discard updates and try again later when it's available -- not
                // doing so would cause the copy of this data in ClickHouse to
                // slowly drift out of sync with the copy in Postgres. This write is
                // safe to retry if we write to Kafka but then fail to commit to
                // Postgres for some reason -- the same row state should be
                // generated each call, and the receiving ReplacingMergeTree will
                // ensure we keep only the latest version after all writes settle.)
                await this.kafkaProducer.queueMessages(messages, true)

                return rows.length
            }
        )

        deferredPersonOverridesProcessedCounter.inc(overridesCount)

        return overridesCount
    }

    public runTask(intervalMs: number): PeriodicTask {
        return new PeriodicTask(
            'processPendingOverrides',
            async () => {
                status.debug('👥', 'Processing pending overrides...')
                const overridesCount = await this.processPendingOverrides()
                ;(overridesCount > 0 ? status.info : status.debug)(
                    '👥',
                    `Processed ${overridesCount} pending overrides.`
                )
            },
            intervalMs
        )
    }
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

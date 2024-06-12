import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { Counter } from 'prom-client'
import { KafkaProducerWrapper } from 'utils/db/kafka-producer-wrapper'

import { KAFKA_PERSON_OVERRIDE } from '../../config/kafka-topics'
import { InternalPerson, Person, PropertyUpdateOperation, TimestampFormat } from '../../types'
import { DB } from '../../utils/db/db'
import { PostgresRouter, PostgresUse, TransactionClient } from '../../utils/db/postgres'
import { eventToPersonProperties, initialEventToPersonProperties, timeoutGuard } from '../../utils/db/utils'
import { PeriodicTask } from '../../utils/periodic-task'
import { promiseRetry } from '../../utils/retries'
import { status } from '../../utils/status'
import { castTimestampOrNow } from '../../utils/utils'
import { uuidFromDistinctId } from './person-uuid'
import { captureIngestionWarning } from './utils'

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

export const personPropertyKeyUpdateCounter = new Counter({
    name: 'person_property_key_update_total',
    help: 'Number of person updates triggered by this property value changing.',
    labelNames: ['key'],
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
const PERSON_EVENTS = new Set(['$identify', '$create_alias', '$merge_dangerously', '$set'])

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

export const isDistinctIdIllegal = (id: string): boolean => {
    const trimmed = id.trim()
    return trimmed === '' || CASE_INSENSITIVE_ILLEGAL_IDS.has(id.toLowerCase()) || CASE_SENSITIVE_ILLEGAL_IDS.has(id)
}

// This class is responsible for creating/updating a single person through the process-event pipeline
export class PersonState {
    private eventProperties: Properties

    public updateIsIdentified: boolean // TODO: remove this from the class and being hidden

    constructor(
        private event: PluginEvent,
        private teamId: number,
        private distinctId: string,
        private timestamp: DateTime,
        private processPerson: boolean, // $process_person_profile flag from the event
        private db: DB,
        private personOverrideWriter?: DeferredPersonOverrideWriter
    ) {
        this.eventProperties = event.properties!

        // If set to true, we'll update `is_identified` at the end of `updateProperties`
        // :KLUDGE: This is an indirect communication channel between `handleIdentifyOrAlias` and `updateProperties`
        this.updateIsIdentified = false
    }

    async update(): Promise<[Person, Promise<void>]> {
        if (!this.processPerson) {
            const existingPerson = await this.db.fetchPerson(this.teamId, this.distinctId, { useReadReplica: true })
            if (existingPerson) {
                const person = existingPerson as Person

                // Ensure person properties don't propagate elsewhere, such as onto the event itself.
                person.properties = {}

                if (this.timestamp > person.created_at.plus({ minutes: 1 })) {
                    // See documentation on the field.
                    //
                    // Note that we account for timestamp vs person creation time (with a little
                    // padding for good measure) to account for ingestion lag. It's possible for
                    // events to be processed after person creation even if they were sent prior
                    // to person creation, and the user did nothing wrong in that case.
                    person.force_upgrade = true
                }

                return [person, Promise.resolve()]
            }

            // We need a value from the `person_created_column` in ClickHouse. This should be
            // hidden from users for events without a real person, anyway. It's slightly offset
            // from the 0 date (by 5 seconds) in order to assist in debugging by being
            // harmlessly distinct from Unix UTC "0".
            const createdAt = DateTime.utc(1970, 1, 1, 0, 0, 5)

            const fakePerson: Person = {
                team_id: this.teamId,
                properties: {},
                uuid: uuidFromDistinctId(this.teamId, this.distinctId),
                created_at: createdAt,
            }
            return [fakePerson, Promise.resolve()]
        }

        const [person, identifyOrAliasKafkaAck]: [InternalPerson | undefined, Promise<void>] =
            await this.handleIdentifyOrAlias() // TODO: make it also return a boolean for if we can exit early here

        if (person) {
            // try to shortcut if we have the person from identify or alias
            try {
                const [updatedPerson, updateKafkaAck] = await this.updatePersonProperties(person)
                return [updatedPerson, Promise.all([identifyOrAliasKafkaAck, updateKafkaAck]).then(() => undefined)]
            } catch (error) {
                // shortcut didn't work, swallow the error and try normal retry loop below
                status.debug('🔁', `failed update after adding distinct IDs, retrying`, { error })
            }
        }

        const [updatedPerson, updateKafkaAck] = await this.handleUpdate()
        return [updatedPerson, Promise.all([identifyOrAliasKafkaAck, updateKafkaAck]).then(() => undefined)]
    }

    async handleUpdate(): Promise<[InternalPerson, Promise<void>]> {
        // There are various reasons why update can fail:
        // - anothe thread created the person during a race
        // - the person might have been merged between start of processing and now
        // we simply and stupidly start from scratch
        return await promiseRetry(() => this.updateProperties(), 'update_person')
    }

    async updateProperties(): Promise<[InternalPerson, Promise<void>]> {
        const [person, propertiesHandled] = await this.createOrGetPerson()
        if (propertiesHandled) {
            return [person, Promise.resolve()]
        }
        return await this.updatePersonProperties(person)
    }

    /**
     * @returns [Person, boolean that indicates if properties were already handled or not]
     */
    private async createOrGetPerson(): Promise<[InternalPerson, boolean]> {
        let person = await this.db.fetchPerson(this.teamId, this.distinctId)
        if (person) {
            return [person, false]
        }

        let properties = {}
        let propertiesOnce = {}
        if (this.processPerson) {
            properties = this.eventProperties['$set']
            propertiesOnce = this.eventProperties['$set_once']
        }

        person = await this.createPerson(
            this.timestamp,
            properties || {},
            propertiesOnce || {},
            this.teamId,
            null,
            // :NOTE: This should never be set in this branch, but adding this for logical consistency
            this.updateIsIdentified,
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
        creatorEventUuid: string,
        distinctIds: string[],
        version = 0
    ): Promise<InternalPerson> {
        if (distinctIds.length < 1) {
            throw new Error('at least 1 distinctId is required in `createPerson`')
        }
        const uuid = uuidFromDistinctId(teamId, distinctIds[0])

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
            distinctIds,
            version
        )
    }

    private async updatePersonProperties(person: InternalPerson): Promise<[InternalPerson, Promise<void>]> {
        person.properties ||= {}

        const update: Partial<InternalPerson> = {}
        if (this.applyEventPropertyUpdates(person.properties)) {
            update.properties = person.properties
        }
        if (this.updateIsIdentified && !person.is_identified) {
            update.is_identified = true
        }

        if (Object.keys(update).length > 0) {
            const [updatedPerson, kafkaMessages] = await this.db.updatePersonDeprecated(person, update)
            const kafkaAck = this.db.kafkaProducer.queueMessages({ kafkaMessages, waitForAck: true })
            return [updatedPerson, kafkaAck]
        }

        return [person, Promise.resolve()]
    }

    // For tracking what property keys cause us to update persons
    // tracking all properties we add from the event, 'geoip' for '$geoip_*' or '$initial_geoip_*' and 'other' for anything outside of those
    private getMetricKey(key: string): string {
        if (key.startsWith('$geoip_') || key.startsWith('$initial_geoip_')) {
            return 'geoIP'
        }
        if (eventToPersonProperties.has(key)) {
            return key
        }
        if (initialEventToPersonProperties.has(key)) {
            return key
        }
        return 'other'
    }

    // Minimize useless person updates by not overriding properties if it's not a person event and we added from the event
    // They will still show up for PoE as it's not removed from the event, we just don't update the person in PG anymore
    private shouldUpdatePersonIfOnlyChange(key: string): boolean {
        if (PERSON_EVENTS.has(this.event.event)) {
            // for person events always update everything
            return true
        }
        // These are properties we add from the event and some change often, it's useless to update person always
        if (eventToPersonProperties.has(key)) {
            return false
        }
        // same as above, coming from GeoIP plugin
        if (key.startsWith('$geoip_')) {
            return false
        }
        return true
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
        // tracking as set because we only care about if other or geoip was the cause of the update, not how many properties got updated
        const metricsKeys = new Set<string>()
        Object.entries(propertiesOnce).map(([key, value]) => {
            if (typeof personProperties[key] === 'undefined') {
                updated = true
                metricsKeys.add(this.getMetricKey(key))
                personProperties[key] = value
            }
        })
        Object.entries(properties).map(([key, value]) => {
            if (personProperties[key] !== value) {
                if (this.shouldUpdatePersonIfOnlyChange(key)) {
                    updated = true
                }
                metricsKeys.add(this.getMetricKey(key))
                personProperties[key] = value
            }
        })
        unsetProperties.forEach((propertyKey) => {
            if (propertyKey in personProperties) {
                updated = true
                metricsKeys.add(this.getMetricKey(propertyKey))
                delete personProperties[propertyKey]
            }
        })
        metricsKeys.forEach((key) => personPropertyKeyUpdateCounter.labels({ key: key }).inc())
        return updated
    }

    // Alias & merge

    async handleIdentifyOrAlias(): Promise<[InternalPerson | undefined, Promise<void>]> {
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
        return [undefined, Promise.resolve()]
    }

    public async merge(
        otherPersonDistinctId: string,
        mergeIntoDistinctId: string,
        teamId: number,
        timestamp: DateTime
    ): Promise<[InternalPerson | undefined, Promise<void>]> {
        // No reason to alias person against itself. Done by posthog-node when updating user properties
        if (mergeIntoDistinctId === otherPersonDistinctId) {
            return [undefined, Promise.resolve()]
        }
        if (isDistinctIdIllegal(mergeIntoDistinctId)) {
            await captureIngestionWarning(
                this.db.kafkaProducer,
                teamId,
                'cannot_merge_with_illegal_distinct_id',
                {
                    illegalDistinctId: mergeIntoDistinctId,
                    otherDistinctId: otherPersonDistinctId,
                    eventUuid: this.event.uuid,
                },
                { alwaysSend: true }
            )
            return [undefined, Promise.resolve()]
        }
        if (isDistinctIdIllegal(otherPersonDistinctId)) {
            await captureIngestionWarning(
                this.db.kafkaProducer,
                teamId,
                'cannot_merge_with_illegal_distinct_id',
                {
                    illegalDistinctId: otherPersonDistinctId,
                    otherDistinctId: mergeIntoDistinctId,
                    eventUuid: this.event.uuid,
                },
                { alwaysSend: true }
            )
            return [undefined, Promise.resolve()]
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
    ): Promise<[InternalPerson, Promise<void>]> {
        this.updateIsIdentified = true

        const otherPerson = await this.db.fetchPerson(teamId, otherPersonDistinctId)
        const mergeIntoPerson = await this.db.fetchPerson(teamId, mergeIntoDistinctId)

        // Historically, we always INSERT-ed new `posthog_persondistinctid` rows with `version=0`.
        // Overrides are only created when the version is > 0, see:
        //   https://github.com/PostHog/posthog/blob/92e17ce307a577c4233d4ab252eebc6c2207a5ee/posthog/models/person/sql.py#L269-L287
        //
        // With the addition of optional person processing, we are no longer creating
        // `posthog_persondistinctid` and `posthog_person` rows when $process_person_profile=false.
        // This means that:
        // 1. At merge time, it's possible this `distinct_id` and its deterministically generated
        //    `person.uuid` has already been used for events in ClickHouse, but they have no
        //    corresponding rows in the `posthog_persondistinctid` or `posthog_person` tables
        // 2. We need to assume the `distinct_id`/`person.uuid` have been used before (by
        //    `$process_person_profile=false` events) and create an override row for this
        //    `distinct_id` even though we're just now INSERT-ing it into Postgres/ClickHouse. We do
        //    this by starting with `version=1`, as if we had just deleted the old user and were
        //    updating the `distinct_id` row as part of the merge
        const addDistinctIdVersion = 1

        if (otherPerson && !mergeIntoPerson) {
            await this.db.addDistinctId(otherPerson, mergeIntoDistinctId, addDistinctIdVersion)
            return [otherPerson, Promise.resolve()]
        } else if (!otherPerson && mergeIntoPerson) {
            await this.db.addDistinctId(mergeIntoPerson, otherPersonDistinctId, addDistinctIdVersion)
            return [mergeIntoPerson, Promise.resolve()]
        } else if (otherPerson && mergeIntoPerson) {
            if (otherPerson.id == mergeIntoPerson.id) {
                return [mergeIntoPerson, Promise.resolve()]
            }
            return await this.mergePeople({
                mergeInto: mergeIntoPerson,
                mergeIntoDistinctId: mergeIntoDistinctId,
                otherPerson: otherPerson,
                otherPersonDistinctId: otherPersonDistinctId,
            })
        }

        //  The last case: (!oldPerson && !newPerson)
        return [
            await this.createPerson(
                // TODO: in this case we could skip the properties updates later
                timestamp,
                this.eventProperties['$set'] || {},
                this.eventProperties['$set_once'] || {},
                teamId,
                null,
                true,
                this.event.uuid,
                [mergeIntoDistinctId, otherPersonDistinctId],
                addDistinctIdVersion
            ),
            Promise.resolve(),
        ]
    }

    public async mergePeople({
        mergeInto,
        mergeIntoDistinctId,
        otherPerson,
        otherPersonDistinctId,
    }: {
        mergeInto: InternalPerson
        mergeIntoDistinctId: string
        otherPerson: InternalPerson
        otherPersonDistinctId: string
    }): Promise<[InternalPerson, Promise<void>]> {
        const olderCreatedAt = DateTime.min(mergeInto.created_at, otherPerson.created_at)
        const mergeAllowed = this.isMergeAllowed(otherPerson)

        // If merge isn't allowed, we will ignore it, log an ingestion warning and exit
        if (!mergeAllowed) {
            await captureIngestionWarning(
                this.db.kafkaProducer,
                this.teamId,
                'cannot_merge_already_identified',
                {
                    sourcePersonDistinctId: otherPersonDistinctId,
                    targetPersonDistinctId: mergeIntoDistinctId,
                    eventUuid: this.event.uuid,
                },
                { alwaysSend: true }
            )
            status.warn('🤔', 'refused to merge an already identified user via an $identify or $create_alias call')
            return [mergeInto, Promise.resolve()] // We're returning the original person tied to distinct_id used for the event
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

        const [mergedPerson, kafkaMessages] = await this.handleMergeTransaction(
            mergeInto,
            otherPerson,
            olderCreatedAt, // Keep the oldest created_at (i.e. the first time we've seen either person)
            properties
        )

        return [mergedPerson, kafkaMessages]
    }

    private isMergeAllowed(mergeFrom: InternalPerson): boolean {
        // $merge_dangerously has no restrictions
        // $create_alias and $identify will not merge a user who's already identified into anyone else
        return this.event.event === '$merge_dangerously' || !mergeFrom.is_identified
    }

    private async handleMergeTransaction(
        mergeInto: InternalPerson,
        otherPerson: InternalPerson,
        createdAt: DateTime,
        properties: Properties
    ): Promise<[InternalPerson, Promise<void>]> {
        mergeTxnAttemptCounter
            .labels({
                call: this.event.event, // $identify, $create_alias or $merge_dangerously
                oldPersonIdentified: String(otherPerson.is_identified),
                newPersonIdentified: String(mergeInto.is_identified),
                poEEmbraceJoin: String(!!this.personOverrideWriter),
            })
            .inc()

        const [mergedPerson, kafkaMessages]: [InternalPerson, ProducerRecord[]] = await this.db.postgres.transaction(
            PostgresUse.COMMON_WRITE,
            'mergePeople',
            async (tx) => {
                const [person, updatePersonMessages] = await this.db.updatePersonDeprecated(
                    mergeInto,
                    {
                        created_at: createdAt,
                        properties: properties,
                        is_identified: true,

                        // By using the max version between the two Persons, we ensure that if
                        // this Person is later split, we can use `this_person.version + 1` for
                        // any split-off Persons and know that *that* version will be higher than
                        // any previously deleted Person, and so the new Person row will "win" and
                        // "undelete" the Person.
                        //
                        // For example:
                        //  - Merge Person_1(version:7) into Person_2(version:2)
                        //      - Person_1 is deleted
                        //      - Person_2 attains version 8 via this code below
                        //  - Person_2 is later split, which attempts to re-create Person_1 by using
                        //    its `distinct_id` to generate the deterministic Person UUID.
                        //    That new Person_1 will have a version _at least_ as high as 8, and
                        //    so any previously existing rows in CH or otherwise from
                        //    Person_1(version:7) will "lose" to this new Person_1.
                        version: Math.max(mergeInto.version, otherPerson.version) + 1,
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

                return [person, [...updatePersonMessages, ...distinctIdMessages, ...deletePersonMessages]]
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

        const kafkaAck = this.db.kafkaProducer.queueMessages({ kafkaMessages, waitForAck: true })

        return [mergedPerson, kafkaAck]
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

function getPersonOverrideDetails(
    teamId: number,
    oldPerson: InternalPerson,
    overridePerson: InternalPerson
): PersonOverrideDetails {
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
                await this.kafkaProducer.queueMessages({ kafkaMessages: messages, waitForAck: true })

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
                const overridesCount = await this.processPendingOverrides(5000)
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

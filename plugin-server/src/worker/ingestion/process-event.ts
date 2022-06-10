import ClickHouse from '@posthog/clickhouse'
import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import crypto from 'crypto'
import equal from 'fast-deep-equal'
import { ProducerRecord } from 'kafkajs'
import { DateTime, Duration } from 'luxon'
import { DatabaseError, PoolClient } from 'pg'

import { Event as EventProto, IEvent } from '../../config/idl/protos'
import { KAFKA_EVENTS, KAFKA_SESSION_RECORDING_EVENTS } from '../../config/kafka-topics'
import {
    Element,
    Event,
    Hub,
    Person,
    PostgresSessionRecordingEvent,
    PreIngestionEvent,
    PropertyUpdateOperation,
    SessionRecordingEvent,
    Team,
    TimestampFormat,
} from '../../types'
import { DB, GroupIdentifier } from '../../utils/db/db'
import { elementsToString, extractElements } from '../../utils/db/elements-chain'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import {
    personInitialAndUTMProperties,
    safeClickhouseString,
    sanitizeEventName,
    timeoutGuard,
} from '../../utils/db/utils'
import { status } from '../../utils/status'
import { castTimestampOrNow, UUID, UUIDT } from '../../utils/utils'
import { KAFKA_BUFFER } from './../../config/kafka-topics'
import { GroupTypeManager } from './group-type-manager'
import { addGroupProperties } from './groups'
import { PersonManager } from './person-manager'
import { upsertGroup } from './properties-updater'
import { TeamManager } from './team-manager'
import { parseDate } from './utils'

const MAX_FAILED_PERSON_MERGE_ATTEMPTS = 3

// for e.g. internal events we don't want to be available for users in the UI
const EVENTS_WITHOUT_EVENT_DEFINITION = ['$$plugin_metrics']

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

export interface EventProcessingResult {
    event: IEvent | SessionRecordingEvent | PostgresSessionRecordingEvent
    eventId?: number
    elements?: Element[]
}

export class EventsProcessor {
    pluginsServer: Hub
    db: DB
    clickhouse: ClickHouse
    kafkaProducer: KafkaProducerWrapper
    teamManager: TeamManager
    personManager: PersonManager
    groupTypeManager: GroupTypeManager
    clickhouseExternalSchemasDisabledTeams: Set<number>

    constructor(pluginsServer: Hub) {
        this.pluginsServer = pluginsServer
        this.db = pluginsServer.db
        this.clickhouse = pluginsServer.clickhouse
        this.kafkaProducer = pluginsServer.kafkaProducer
        this.teamManager = pluginsServer.teamManager
        this.personManager = new PersonManager(pluginsServer)
        this.groupTypeManager = new GroupTypeManager(pluginsServer.db, this.teamManager, pluginsServer.SITE_URL)
        this.clickhouseExternalSchemasDisabledTeams = new Set(
            pluginsServer.CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS_TEAMS.split(',').filter(String).map(Number)
        )
    }

    public async processEvent(
        distinctId: string,
        ip: string | null,
        data: PluginEvent,
        teamId: number,
        now: DateTime,
        sentAt: DateTime | null,
        eventUuid: string
    ): Promise<PreIngestionEvent | null> {
        if (!UUID.validateString(eventUuid, false)) {
            throw new Error(`Not a valid UUID: "${eventUuid}"`)
        }
        const singleSaveTimer = new Date()
        const timeout = timeoutGuard('Still inside "EventsProcessor.processEvent". Timeout warning after 30 sec!', {
            event: JSON.stringify(data),
        })

        let result: PreIngestionEvent | null = null
        try {
            // Sanitize values, even though `sanitizeEvent` should have gotten to them
            const properties: Properties = data.properties ?? {}
            if (data['$set']) {
                properties['$set'] = { ...properties['$set'], ...data['$set'] }
            }
            if (data['$set_once']) {
                properties['$set_once'] = { ...properties['$set_once'], ...data['$set_once'] }
            }

            const personUuid = new UUIDT().toString()

            // TODO: we should just handle all person's related changes together not here and in capture separately
            const parsedTs = this.handleTimestamp(data, now, sentAt)
            const ts = parsedTs.isValid ? parsedTs : DateTime.now()
            if (!parsedTs.isValid) {
                this.pluginsServer.statsd?.increment('process_event_invalid_timestamp', { teamId: String(teamId) })
            }
            const timeout1 = timeoutGuard('Still running "handleIdentifyOrAlias". Timeout warning after 30 sec!', {
                eventUuid,
            })
            try {
                await this.handleIdentifyOrAlias(data['event'], properties, distinctId, teamId, ts)
            } catch (e) {
                console.error('handleIdentifyOrAlias failed', e, data)
            } finally {
                clearTimeout(timeout1)
            }

            const team = await this.teamManager.fetchTeam(teamId)
            if (!team) {
                throw new Error(`No team found with ID ${teamId}. Can't ingest event.`)
            }

            if (data['event'] === '$snapshot') {
                if (team.session_recording_opt_in) {
                    const timeout2 = timeoutGuard(
                        'Still running "createSessionRecordingEvent". Timeout warning after 30 sec!',
                        { eventUuid }
                    )
                    try {
                        result = await this.createSessionRecordingEvent(
                            eventUuid,
                            teamId,
                            distinctId,
                            properties['$session_id'],
                            properties['$window_id'],
                            ts,
                            properties['$snapshot_data'],
                            properties,
                            personUuid,
                            ip
                        )
                        this.pluginsServer.statsd?.timing('kafka_queue.single_save.snapshot', singleSaveTimer, {
                            team_id: teamId.toString(),
                        })
                        // No return value in case of snapshot events as we don't do action matching on them
                    } finally {
                        clearTimeout(timeout2)
                    }
                }
            } else {
                const timeout3 = timeoutGuard('Still running "capture". Timeout warning after 30 sec!', { eventUuid })
                try {
                    result = await this.capture(
                        eventUuid,
                        personUuid,
                        ip,
                        team,
                        data['event'],
                        distinctId,
                        properties,
                        ts
                    )
                    this.pluginsServer.statsd?.timing('kafka_queue.single_save.standard', singleSaveTimer, {
                        team_id: teamId.toString(),
                    })
                } finally {
                    clearTimeout(timeout3)
                }
            }
        } finally {
            clearTimeout(timeout)
        }
        return result
    }

    public handleTimestamp(data: PluginEvent, now: DateTime, sentAt: DateTime | null): DateTime {
        if (data['timestamp']) {
            if (sentAt) {
                // sent_at - timestamp == now - x
                // x = now + (timestamp - sent_at)
                try {
                    // timestamp and sent_at must both be in the same format: either both with or both without timezones
                    // otherwise we can't get a diff to add to now
                    return now.plus(parseDate(data['timestamp']).diff(sentAt))
                } catch (error) {
                    status.error('⚠️', 'Error when handling timestamp:', error)
                    Sentry.captureException(error, { extra: { data, now, sentAt } })
                }
            }
            return parseDate(data['timestamp'])
        }
        if (data['offset']) {
            return now.minus(Duration.fromMillis(data['offset']))
        }
        return now
    }

    public clickhouseExternalSchemasEnabled(teamId: number): boolean {
        if (this.pluginsServer.CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS) {
            return false
        }
        return !this.clickhouseExternalSchemasDisabledTeams.has(teamId)
    }

    private async updatePersonProperties(
        teamId: number,
        distinctId: string,
        properties: Properties,
        propertiesOnce: Properties,
        unsetProperties: Array<string>
    ): Promise<void> {
        await this.updatePersonPropertiesDeprecated(teamId, distinctId, properties, propertiesOnce, unsetProperties)
    }

    private async updatePersonPropertiesDeprecated(
        teamId: number,
        distinctId: string,
        properties: Properties,
        propertiesOnce: Properties,
        unsetProperties: Array<string>
    ): Promise<void> {
        const personFound = await this.db.fetchPerson(teamId, distinctId)
        if (!personFound) {
            this.pluginsServer.statsd?.increment('person_not_found', { teamId: String(teamId), key: 'update' })
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

    private async setIsIdentified(teamId: number, distinctId: string, isIdentified = true): Promise<void> {
        const personFound = await this.db.fetchPerson(teamId, distinctId)
        if (!personFound) {
            this.pluginsServer.statsd?.increment('person_not_found', { teamId: String(teamId), key: 'identify' })
            throw new Error(`Could not find person with distinct id "${distinctId}" in team "${teamId}" to identify`)
        }
        if (personFound && !personFound.is_identified) {
            await this.db.updatePersonDeprecated(personFound, { is_identified: isIdentified })
        }
    }

    private async handleIdentifyOrAlias(
        event: string,
        properties: Properties,
        distinctId: string,
        teamId: number,
        timestamp: DateTime
    ): Promise<void> {
        if (isDistinctIdIllegal(distinctId)) {
            this.pluginsServer.statsd?.increment(`illegal_distinct_ids.total`, { distinctId })
            return
        }
        if (event === '$create_alias') {
            await this.merge(properties['alias'], distinctId, teamId, timestamp, false)
        } else if (event === '$identify' && properties['$anon_distinct_id']) {
            await this.merge(properties['$anon_distinct_id'], distinctId, teamId, timestamp, true)
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
        const newPerson = await this.db.fetchPerson(teamId, distinctId)

        if (oldPerson && !newPerson) {
            try {
                await this.db.addDistinctId(oldPerson, distinctId)
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
                await this.createPerson(timestamp, {}, {}, teamId, null, shouldIdentifyPerson, new UUIDT().toString(), [
                    distinctId,
                    previousDistinctId,
                ])
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
        }

        if (shouldIdentifyPerson) {
            await this.setIsIdentified(teamId, distinctId)
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
                const updatePersonMessages = await this.db.updatePersonDeprecated(
                    mergeInto,
                    {
                        created_at: firstSeen,
                        properties: mergeInto.properties,
                        is_identified: mergeInto.is_identified || otherPerson.is_identified,
                    },
                    client
                )

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

        await this.kafkaProducer.queueMessages(kafkaMessages)
    }

    private async capture(
        eventUuid: string,
        personUuid: string,
        ip: string | null,
        team: Team,
        event: string,
        distinctId: string,
        properties: Properties,
        timestamp: DateTime
    ): Promise<PreIngestionEvent> {
        event = sanitizeEventName(event)
        const elements: Record<string, any>[] | undefined = properties['$elements']
        let elementsList: Element[] = []

        if (elements && elements.length) {
            delete properties['$elements']
            elementsList = extractElements(elements)
        }

        if (ip && !team.anonymize_ips && !('$ip' in properties)) {
            properties['$ip'] = ip
        }

        if (!EVENTS_WITHOUT_EVENT_DEFINITION.includes(event)) {
            await this.teamManager.updateEventNamesAndProperties(team.id, event, properties)
        }

        properties = personInitialAndUTMProperties(properties)
        properties = await addGroupProperties(team.id, properties, this.groupTypeManager)

        const createdNewPersonWithProperties = await this.createPersonIfDistinctIdIsNew(
            team.id,
            distinctId,
            timestamp,
            personUuid,
            properties['$set'],
            properties['$set_once']
        )

        if (event === '$groupidentify') {
            await this.upsertGroup(team.id, properties, timestamp)
        } else if (
            !createdNewPersonWithProperties &&
            (properties['$set'] || properties['$set_once'] || properties['$unset'])
        ) {
            await this.updatePersonProperties(
                team.id,
                distinctId,
                properties['$set'] || {},
                properties['$set_once'] || {},
                properties['$unset'] || []
            )
        }

        return {
            eventUuid,
            event,
            ip,
            distinctId,
            properties,
            timestamp,
            elementsList,
            teamId: team.id,
        }
    }

    getGroupIdentifiers(properties: Properties): GroupIdentifier[] {
        const res: GroupIdentifier[] = []
        for (let index = 0; index < this.db.MAX_GROUP_TYPES_PER_TEAM; index++) {
            const key = `$group_${index}`
            if (properties.hasOwnProperty(key)) {
                res.push({ index: index, key: properties[key] })
            }
        }
        return res
    }

    async createEvent(
        preIngestionEvent: PreIngestionEvent
    ): Promise<[IEvent, Event['id'] | undefined, Element[] | undefined]> {
        const {
            eventUuid: uuid,
            event,
            teamId,
            distinctId,
            properties,
            timestamp,
            elementsList: elements,
        } = preIngestionEvent

        const timestampFormat = this.kafkaProducer ? TimestampFormat.ClickHouse : TimestampFormat.ISO
        const timestampString = castTimestampOrNow(timestamp, timestampFormat)

        const elementsChain = elements && elements.length ? elementsToString(elements) : ''

        const personInfo = await this.db.getPersonData(teamId, distinctId)
        const groupProperties = await this.db.getGroupProperties(teamId, this.getGroupIdentifiers(properties))

        let eventPersonProperties: string | null = null
        if (personInfo) {
            // For consistency, we'd like events to contain the properties that they set, even if those were changed
            // before the event is ingested. Thus we fetch the updated properties but override the values with the event's
            // $set properties if they exist.
            const latestPersonProperties = personInfo ? personInfo?.properties : {}
            eventPersonProperties = JSON.stringify({ ...latestPersonProperties, ...(properties.$set || {}) })
        }

        const eventPayload: IEvent = {
            uuid,
            event: safeClickhouseString(event),
            properties: JSON.stringify(properties ?? {}),
            timestamp: timestampString,
            team_id: teamId,
            distinct_id: safeClickhouseString(distinctId),
            elements_chain: safeClickhouseString(elementsChain),
            created_at: castTimestampOrNow(null, timestampFormat),
        }

        let eventId: Event['id'] | undefined

        const useExternalSchemas = this.clickhouseExternalSchemasEnabled(teamId)
        // proto ingestion is deprecated and we won't support new additions to the schema
        const message = useExternalSchemas
            ? (EventProto.encodeDelimited(EventProto.create(eventPayload)).finish() as Buffer)
            : Buffer.from(
                  JSON.stringify({
                      ...eventPayload,
                      person_id: personInfo?.uuid,
                      person_properties: eventPersonProperties,
                      ...groupProperties,
                  })
              )

        await this.kafkaProducer.queueMessage({
            topic: useExternalSchemas ? KAFKA_EVENTS : this.pluginsServer.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
            messages: [
                {
                    key: uuid,
                    value: message,
                },
            ],
        })

        return [eventPayload, eventId, elements]
    }

    async produceEventToBuffer(bufferEvent: PreIngestionEvent): Promise<void> {
        const partitionKeyHash = crypto.createHash('sha256')
        partitionKeyHash.update(`${bufferEvent.teamId}:${bufferEvent.distinctId}`)
        const partitionKey = partitionKeyHash.digest('hex')

        await this.kafkaProducer.queueSingleJsonMessage(KAFKA_BUFFER, partitionKey, bufferEvent)
    }

    private async createSessionRecordingEvent(
        uuid: string,
        team_id: number,
        distinct_id: string,
        session_id: string,
        window_id: string,
        timestamp: DateTime,
        snapshot_data: Record<any, any>,
        properties: Properties,
        personUuid: string,
        ip: string | null
    ): Promise<PreIngestionEvent> {
        const timestampString = castTimestampOrNow(
            timestamp,
            this.kafkaProducer ? TimestampFormat.ClickHouse : TimestampFormat.ISO
        )

        await this.createPersonIfDistinctIdIsNew(team_id, distinct_id, timestamp, personUuid.toString())

        const data: SessionRecordingEvent = {
            uuid,
            team_id: team_id,
            distinct_id: distinct_id,
            session_id: session_id,
            window_id: window_id,
            snapshot_data: JSON.stringify(snapshot_data),
            timestamp: timestampString,
            created_at: timestampString,
        }

        await this.kafkaProducer.queueSingleJsonMessage(KAFKA_SESSION_RECORDING_EVENTS, uuid, data)

        return {
            eventUuid: uuid,
            event: '$snapshot',
            ip,
            distinctId: distinct_id,
            properties,
            timestamp: timestampString,
            elementsList: [],
            teamId: team_id,
        }
    }

    private async createPersonIfDistinctIdIsNew(
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

    private async upsertGroup(teamId: number, properties: Properties, timestamp: DateTime): Promise<void> {
        if (!properties['$group_type'] || !properties['$group_key']) {
            return
        }

        const { $group_type: groupType, $group_key: groupKey, $group_set: groupPropertiesToSet } = properties
        const groupTypeIndex = await this.groupTypeManager.fetchGroupTypeIndex(teamId, groupType)

        if (groupTypeIndex !== null) {
            await upsertGroup(
                this.db,
                teamId,
                groupTypeIndex,
                groupKey.toString(),
                groupPropertiesToSet || {},
                timestamp
            )
        }
    }

    private async handleTablesDependingOnPersonID(
        sourcePerson: Person,
        targetPerson: Person,
        client?: PoolClient
    ): Promise<undefined> {
        // When personIDs change, update places depending on a person_id foreign key

        // For Cohorts
        await this.db.postgresQuery(
            'UPDATE posthog_cohortpeople SET person_id = $1 WHERE person_id = $2',
            [targetPerson.id, sourcePerson.id],
            'updateCohortPeople',
            client
        )

        // For FeatureFlagHashKeyOverrides
        const allOverrides = await this.db.postgresQuery(
            'SELECT id, person_id, feature_flag_key FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 AND person_id = ANY($2)',
            [sourcePerson.team_id, [sourcePerson.id, targetPerson.id]],
            'selectFeatureFlagHashKeyOverride'
        )

        if (allOverrides.rowCount === 0) {
            return
        }

        // Update where feature_flag_key exists for sourcePerson but not for targetPerson
        const sourceOverrides = allOverrides.rows.filter((override) => override.person_id == sourcePerson.id)
        const targetOverrideKeys = allOverrides.rows
            .filter((override) => override.person_id == targetPerson.id)
            .map((override) => override.feature_flag_key)

        const itemsToUpdate = sourceOverrides
            .filter((override) => !targetOverrideKeys.includes(override.feature_flag_key))
            .map((override) => override.id)

        if (itemsToUpdate.length !== 0) {
            await this.db.postgresQuery(
                `UPDATE posthog_featureflaghashkeyoverride SET person_id = $1 WHERE person_id = $2 AND id = ANY($3)
                `,
                [targetPerson.id, sourcePerson.id, itemsToUpdate],
                'updateFeatureFlagHashKeyOverride',
                client
            )
        }

        // delete all other instances
        // necessary to make sure person can then be deleted
        if (sourceOverrides.length !== 0) {
            await this.db.postgresQuery(
                'DELETE FROM posthog_featureflaghashkeyoverride WHERE person_id = $1',
                [sourcePerson.id],
                'deleteFeatureFlagHashKeyOverride',
                client
            )
        }
    }
}

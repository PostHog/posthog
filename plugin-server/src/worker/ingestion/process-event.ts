import ClickHouse from '@posthog/clickhouse'
import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import equal from 'fast-deep-equal'
import { ProducerRecord } from 'kafkajs'
import { DateTime, Duration } from 'luxon'
import { DatabaseError, QueryResult } from 'pg'

import { Event as EventProto, IEvent } from '../../config/idl/protos'
import { KAFKA_EVENTS, KAFKA_SESSION_RECORDING_EVENTS } from '../../config/kafka-topics'
import {
    Element,
    Event,
    Hub,
    Person,
    PostgresSessionRecordingEvent,
    SessionRecordingEvent,
    TeamId,
    TimestampFormat,
} from '../../types'
import { Client } from '../../utils/celery/client'
import { DB } from '../../utils/db/db'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import {
    elementsToString,
    extractElements,
    personInitialAndUTMProperties,
    sanitizeEventName,
    timeoutGuard,
} from '../../utils/db/utils'
import { status } from '../../utils/status'
import { castTimestampOrNow, RaceConditionError, UUID, UUIDT } from '../../utils/utils'
import { GroupTypeManager } from './group-type-manager'
import { addGroupProperties } from './groups'
import { PersonManager } from './person-manager'
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
    clickhouse: ClickHouse | undefined
    kafkaProducer: KafkaProducerWrapper | undefined
    celery: Client
    teamManager: TeamManager
    personManager: PersonManager
    groupTypeManager: GroupTypeManager

    constructor(pluginsServer: Hub) {
        this.pluginsServer = pluginsServer
        this.db = pluginsServer.db
        this.clickhouse = pluginsServer.clickhouse
        this.kafkaProducer = pluginsServer.kafkaProducer
        this.celery = new Client(pluginsServer.db, pluginsServer.CELERY_DEFAULT_QUEUE)
        this.teamManager = pluginsServer.teamManager
        this.personManager = new PersonManager(pluginsServer)
        this.groupTypeManager = new GroupTypeManager(pluginsServer.db)
    }

    public async processEvent(
        distinctId: string,
        ip: string | null,
        siteUrl: string,
        data: PluginEvent,
        teamId: number,
        now: DateTime,
        sentAt: DateTime | null,
        eventUuid: string
    ): Promise<EventProcessingResult | void> {
        if (!UUID.validateString(eventUuid, false)) {
            throw new Error(`Not a valid UUID: "${eventUuid}"`)
        }
        const singleSaveTimer = new Date()
        const timeout = timeoutGuard('Still inside "EventsProcessor.processEvent". Timeout warning after 30 sec!', {
            event: JSON.stringify(data),
        })

        let result: EventProcessingResult | void
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

            const ts = this.handleTimestamp(data, now, sentAt)
            const timeout1 = timeoutGuard('Still running "handleIdentifyOrAlias". Timeout warning after 30 sec!', {
                eventUuid,
            })
            try {
                await this.handleIdentifyOrAlias(data['event'], properties, distinctId, teamId)
            } catch (e) {
                console.error('handleIdentifyOrAlias failed', e, data)
                Sentry.captureException(e, { extra: { event: data } })
            } finally {
                clearTimeout(timeout1)
            }

            if (data['event'] === '$snapshot') {
                const timeout2 = timeoutGuard(
                    'Still running "createSessionRecordingEvent". Timeout warning after 30 sec!',
                    { eventUuid }
                )
                try {
                    await this.createSessionRecordingEvent(
                        eventUuid,
                        teamId,
                        distinctId,
                        properties['$session_id'],
                        ts,
                        properties['$snapshot_data'],
                        personUuid
                    )
                    this.pluginsServer.statsd?.timing('kafka_queue.single_save.snapshot', singleSaveTimer, {
                        team_id: teamId.toString(),
                    })
                    // No return value in case of snapshot events as we don't do action matching on them
                } finally {
                    clearTimeout(timeout2)
                }
            } else {
                const timeout3 = timeoutGuard('Still running "capture". Timeout warning after 30 sec!', { eventUuid })
                try {
                    const [event, eventId, elements] = await this.capture(
                        eventUuid,
                        personUuid,
                        ip,
                        siteUrl,
                        teamId,
                        data['event'],
                        distinctId,
                        properties,
                        ts,
                        sentAt
                    )
                    this.pluginsServer.statsd?.timing('kafka_queue.single_save.standard', singleSaveTimer, {
                        team_id: teamId.toString(),
                    })
                    result = {
                        event,
                        eventId,
                        elements,
                    }
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

    private async updatePersonProperties(
        teamId: number,
        distinctId: string,
        properties: Properties,
        propertiesOnce: Properties
    ): Promise<void> {
        const personFound = await this.db.fetchPerson(teamId, distinctId)
        if (!personFound) {
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

        const arePersonsEqual = equal(personFound.properties, updatedProperties)

        if (arePersonsEqual && !this.db.kafkaProducer) {
            return
        }

        await this.db.updatePerson(personFound, { properties: updatedProperties })
    }

    private async setIsIdentified(teamId: number, distinctId: string, isIdentified = true): Promise<void> {
        const personFound = await this.db.fetchPerson(teamId, distinctId)
        if (!personFound) {
            throw new Error(`Could not find person with distinct id "${distinctId}" in team "${teamId}" to identify`)
        }
        if (personFound && !personFound.is_identified) {
            await this.db.updatePerson(personFound, { is_identified: isIdentified })
        }
    }

    private async handleIdentifyOrAlias(
        event: string,
        properties: Properties,
        distinctId: string,
        teamId: number
    ): Promise<void> {
        if (isDistinctIdIllegal(distinctId)) {
            this.pluginsServer.statsd?.increment(`illegal_distinct_ids.total`, { distinctId })
            return
        }
        if (event === '$create_alias') {
            await this.alias(properties['alias'], distinctId, teamId, false)
        } else if (event === '$identify' && properties['$anon_distinct_id']) {
            await this.alias(properties['$anon_distinct_id'], distinctId, teamId)
        }
    }

    private async alias(
        previousDistinctId: string,
        distinctId: string,
        teamId: number,
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
                    await this.alias(previousDistinctId, distinctId, teamId, shouldIdentifyPerson, false)
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
                    await this.alias(previousDistinctId, distinctId, teamId, shouldIdentifyPerson, false)
                }
            }
        } else if (!oldPerson && !newPerson) {
            try {
                await this.db.createPerson(
                    DateTime.utc(),
                    {},
                    teamId,
                    null,
                    shouldIdentifyPerson,
                    new UUIDT().toString(),
                    [distinctId, previousDistinctId]
                )
            } catch {
                // Catch race condition where in between getting and creating,
                // another request already created this person
                if (retryIfFailed) {
                    // Try once more, probably one of the two persons exists now
                    await this.alias(previousDistinctId, distinctId, teamId, shouldIdentifyPerson, false)
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
        totalMergeAttempts = 0,
        shouldIdentifyPerson = true,
    }: {
        mergeInto: Person
        mergeIntoDistinctId: string
        otherPerson: Person
        otherPersonDistinctId: string
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
                const updatePersonMessages = await this.db.updatePerson(
                    mergeInto,
                    {
                        created_at: firstSeen,
                        properties: mergeInto.properties,
                        is_identified: mergeInto.is_identified || otherPerson.is_identified,
                    },
                    client
                )

                // Merge the distinct IDs
                await client.query('UPDATE posthog_cohortpeople SET person_id = $1 WHERE person_id = $2', [
                    mergeInto.id,
                    otherPerson.id,
                ])

                const distinctIdMessages = await this.db.moveDistinctIds(otherPerson, mergeInto)

                const deletePersonMessages = await this.db.deletePerson(otherPerson, client)

                kafkaMessages = [...updatePersonMessages, ...distinctIdMessages, ...deletePersonMessages]
            } catch (error) {
                Sentry.captureException(error, {
                    extra: { mergeInto, mergeIntoDistinctId, otherPerson, otherPersonDistinctId },
                })

                if (!(error instanceof DatabaseError)) {
                    throw error // Very much not OK, this is some completely unexpected error
                }

                failedAttempts++
                if (failedAttempts === MAX_FAILED_PERSON_MERGE_ATTEMPTS) {
                    throw error // Very much not OK, failed repeatedly so rethrowing the error
                }

                await this.alias(
                    otherPersonDistinctId,
                    mergeIntoDistinctId,
                    teamId,
                    shouldIdentifyPerson,
                    false,
                    failedAttempts
                )
            }
        })

        if (this.kafkaProducer) {
            for (const kafkaMessage of kafkaMessages) {
                await this.kafkaProducer.queueMessage(kafkaMessage)
            }
        }
    }

    private async capture(
        eventUuid: string,
        personUuid: string,
        ip: string | null,
        siteUrl: string,
        teamId: number,
        event: string,
        distinctId: string,
        properties: Properties,
        timestamp: DateTime,
        sentAt: DateTime | null
    ): Promise<[IEvent, Event['id'] | undefined, Element[] | undefined]> {
        event = sanitizeEventName(event)
        const elements: Record<string, any>[] | undefined = properties['$elements']
        let elementsList: Element[] = []

        if (elements && elements.length) {
            delete properties['$elements']
            elementsList = extractElements(elements)
        }

        const team = await this.teamManager.fetchTeam(teamId)

        if (!team) {
            throw new Error(`No team found with ID ${teamId}. Can't ingest event.`)
        }

        if (ip && !team.anonymize_ips && !('$ip' in properties)) {
            properties['$ip'] = ip
        }

        if (!EVENTS_WITHOUT_EVENT_DEFINITION.includes(event)) {
            await this.teamManager.updateEventNamesAndProperties(teamId, event, properties)
        }

        await this.createPersonIfDistinctIdIsNew(teamId, distinctId, sentAt || DateTime.utc(), personUuid)

        properties = personInitialAndUTMProperties(properties)
        properties = await addGroupProperties(teamId, properties, this.groupTypeManager)

        if (event === '$groupidentify') {
            await this.upsertGroup(teamId, properties)
        } else if (properties['$set'] || properties['$set_once']) {
            await this.updatePersonProperties(
                teamId,
                distinctId,
                properties['$set'] || {},
                properties['$set_once'] || {}
            )
        }

        return await this.createEvent(
            eventUuid,
            event,
            teamId,
            distinctId,
            properties,
            timestamp,
            elementsList,
            siteUrl
        )
    }

    private async createEvent(
        uuid: string,
        event: string,
        teamId: TeamId,
        distinctId: string,
        properties?: Properties,
        timestamp?: DateTime | string,
        elements?: Element[],
        siteUrl?: string
    ): Promise<[IEvent, Event['id'] | undefined, Element[] | undefined]> {
        const timestampString = castTimestampOrNow(
            timestamp,
            this.kafkaProducer ? TimestampFormat.ClickHouse : TimestampFormat.ISO
        )
        const elementsChain = elements && elements.length ? elementsToString(elements) : ''

        const eventPayload: IEvent = {
            uuid,
            event,
            properties: JSON.stringify(properties ?? {}),
            timestamp: timestampString,
            teamId,
            distinctId,
            elementsChain,
            createdAt: castTimestampOrNow(),
        }

        let eventId: Event['id'] | undefined

        if (this.kafkaProducer) {
            await this.kafkaProducer.queueMessage({
                topic: KAFKA_EVENTS,
                messages: [
                    {
                        key: uuid,
                        value: EventProto.encodeDelimited(EventProto.create(eventPayload)).finish() as Buffer,
                    },
                ],
            })
        } else {
            let elementsHash = ''
            if (elements && elements.length > 0) {
                elementsHash = await this.db.createElementGroup(elements, teamId)
            }
            const {
                rows: [event],
            } = await this.db.postgresQuery(
                'INSERT INTO posthog_event (created_at, event, distinct_id, properties, team_id, timestamp, elements, elements_hash) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *',
                [
                    eventPayload.createdAt,
                    eventPayload.event,
                    distinctId,
                    eventPayload.properties,
                    eventPayload.teamId,
                    eventPayload.timestamp,
                    JSON.stringify(elements || []),
                    elementsHash,
                ],
                'createEventInsert'
            )
            eventId = event.id
        }

        return [eventPayload, eventId, elements]
    }

    private async createSessionRecordingEvent(
        uuid: string,
        team_id: number,
        distinct_id: string,
        session_id: string,
        timestamp: DateTime | string,
        snapshot_data: Record<any, any>,
        personUuid: string
    ): Promise<SessionRecordingEvent | PostgresSessionRecordingEvent> {
        const timestampString = castTimestampOrNow(
            timestamp,
            this.kafkaProducer ? TimestampFormat.ClickHouse : TimestampFormat.ISO
        )

        await this.createPersonIfDistinctIdIsNew(team_id, distinct_id, DateTime.utc(), personUuid.toString())

        const data: SessionRecordingEvent = {
            uuid,
            team_id: team_id,
            distinct_id: distinct_id,
            session_id: session_id,
            snapshot_data: JSON.stringify(snapshot_data),
            timestamp: timestampString,
            created_at: timestampString,
        }

        if (this.kafkaProducer) {
            await this.kafkaProducer.queueMessage({
                topic: KAFKA_SESSION_RECORDING_EVENTS,
                messages: [{ key: uuid, value: Buffer.from(JSON.stringify(data)) }],
            })
        } else {
            const {
                rows: [eventCreated],
            } = await this.db.postgresQuery(
                'INSERT INTO posthog_sessionrecordingevent (created_at, team_id, distinct_id, session_id, timestamp, snapshot_data) VALUES ($1, $2, $3, $4, $5, $6) RETURNING *',
                [data.created_at, data.team_id, data.distinct_id, data.session_id, data.timestamp, data.snapshot_data],
                'insertSessionRecording'
            )
            return eventCreated as PostgresSessionRecordingEvent
        }
        return data
    }

    private async createPersonIfDistinctIdIsNew(
        teamId: number,
        distinctId: string,
        sentAt: DateTime,
        personUuid: string
    ): Promise<void> {
        const isNewPerson = await this.personManager.isNewPerson(this.db, teamId, distinctId)
        if (isNewPerson) {
            // Catch race condition where in between getting and creating, another request already created this user
            try {
                await this.db.createPerson(sentAt, {}, teamId, null, false, personUuid.toString(), [distinctId])
            } catch (error) {
                if (!error.message || !error.message.includes('duplicate key value violates unique constraint')) {
                    Sentry.captureException(error, { extra: { teamId, distinctId, sentAt, personUuid } })
                }
            }
        }
    }

    // :TODO: Support _updating_ part of properties, not just setting everything at once.
    private async upsertGroup(teamId: number, properties: Properties): Promise<void> {
        if (!properties['$group_type'] || !properties['$group_key']) {
            return
        }

        const { $group_type: groupType, $group_key: groupKey, $group_set: groupPropertiesToSet } = properties
        const groupTypeIndex = await this.groupTypeManager.fetchGroupTypeIndex(teamId, groupType)

        if (groupTypeIndex !== null) {
            await this.db.upsertGroup(teamId, groupTypeIndex, groupKey, groupPropertiesToSet || {})
        }
    }
}

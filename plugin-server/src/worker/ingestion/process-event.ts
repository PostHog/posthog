import ClickHouse from '@posthog/clickhouse'
import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import crypto from 'crypto'
import { DateTime, Duration } from 'luxon'

import { Event as EventProto, IEvent } from '../../config/idl/protos'
import { KAFKA_EVENTS, KAFKA_SESSION_RECORDING_EVENTS } from '../../config/kafka-topics'
import {
    Element,
    Event,
    Hub,
    PostgresSessionRecordingEvent,
    PreIngestionEvent,
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
import { castTimestampOrNow, UUID } from '../../utils/utils'
import { KAFKA_BUFFER } from './../../config/kafka-topics'
import { GroupTypeManager } from './group-type-manager'
import { addGroupProperties } from './groups'
import { PersonManager } from './person-manager'
import { PersonStateManager } from './person-state-manager'
import { upsertGroup } from './properties-updater'
import { TeamManager } from './team-manager'
import { parseDate } from './utils'

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

            // TODO: we should just handle all person's related changes together not here and in capture separately
            const parsedTs = this.handleTimestamp(data, now, sentAt)
            const ts = parsedTs.isValid ? parsedTs : DateTime.now()
            if (!parsedTs.isValid) {
                this.pluginsServer.statsd?.increment('process_event_invalid_timestamp', { teamId: String(teamId) })
            }
            const timeout1 = timeoutGuard('Still running "handleIdentifyOrAlias". Timeout warning after 30 sec!', {
                eventUuid,
            })

            const team = await this.teamManager.fetchTeam(teamId)
            if (!team) {
                throw new Error(`No team found with ID ${teamId}. Can't ingest event.`)
            }

            const personStateManager = new PersonStateManager(
                ts,
                this.db,
                this.pluginsServer.statsd,
                this.personManager
            )
            try {
                await personStateManager.handleIdentifyOrAlias(data['event'], properties, distinctId, teamId, ts)
            } catch (e) {
                console.error('handleIdentifyOrAlias failed', e, data)
            } finally {
                clearTimeout(timeout1)
            }

            if (data['event'] === '$snapshot') {
                if (team.session_recording_opt_in) {
                    const timeout2 = timeoutGuard(
                        'Still running "createSessionRecordingEvent". Timeout warning after 30 sec!',
                        { eventUuid }
                    )
                    try {
                        result = await this.createSessionRecordingEvent(
                            personStateManager,
                            eventUuid,
                            teamId,
                            distinctId,
                            properties['$session_id'],
                            properties['$window_id'],
                            ts,
                            properties['$snapshot_data'],
                            properties,
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
                        personStateManager,
                        eventUuid,
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

    private async capture(
        personStateManager: PersonStateManager,
        eventUuid: string,
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

        properties = personInitialAndUTMProperties(properties)
        await this.teamManager.updateEventNamesAndProperties(team.id, event, properties)
        properties = await addGroupProperties(team.id, properties, this.groupTypeManager)

        const createdNewPersonWithProperties = await personStateManager.createPersonIfDistinctIdIsNew(
            team.id,
            distinctId,
            timestamp,
            personStateManager.newUuid,
            properties['$set'],
            properties['$set_once']
        )

        if (event === '$groupidentify') {
            await this.upsertGroup(team.id, properties, timestamp)
        } else if (
            !createdNewPersonWithProperties &&
            (properties['$set'] || properties['$set_once'] || properties['$unset'])
        ) {
            await personStateManager.updatePersonProperties(
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
        personStateManager: PersonStateManager,
        uuid: string,
        team_id: number,
        distinct_id: string,
        session_id: string,
        window_id: string,
        timestamp: DateTime,
        snapshot_data: Record<any, any>,
        properties: Properties,
        ip: string | null
    ): Promise<PreIngestionEvent> {
        const timestampString = castTimestampOrNow(
            timestamp,
            this.kafkaProducer ? TimestampFormat.ClickHouse : TimestampFormat.ISO
        )

        await personStateManager.createPersonIfDistinctIdIsNew(
            team_id,
            distinct_id,
            timestamp,
            personStateManager.newUuid
        )

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
}

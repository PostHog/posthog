import ClickHouse from '@posthog/clickhouse'
import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import crypto from 'crypto'
import { DateTime } from 'luxon'

import { Event as EventProto, IEvent } from '../../config/idl/protos'
import { KAFKA_EVENTS, KAFKA_SESSION_RECORDING_EVENTS } from '../../config/kafka-topics'
import {
    Element,
    Hub,
    IngestionEvent,
    Person,
    PostgresSessionRecordingEvent,
    PreIngestionEvent,
    SessionRecordingEvent,
    Team,
    TimestampFormat,
} from '../../types'
import { DB, GroupIdentifier } from '../../utils/db/db'
import { elementsToString, extractElements } from '../../utils/db/elements-chain'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import { safeClickhouseString, sanitizeEventName, timeoutGuard } from '../../utils/db/utils'
import { castTimestampOrNow, UUID } from '../../utils/utils'
import { KAFKA_BUFFER } from './../../config/kafka-topics'
import { GroupTypeManager } from './group-type-manager'
import { addGroupProperties } from './groups'
import { PersonState } from './person-state'
import { upsertGroup } from './properties-updater'
import { TeamManager } from './team-manager'

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
    groupTypeManager: GroupTypeManager
    clickhouseExternalSchemasDisabledTeams: Set<number>

    constructor(pluginsServer: Hub) {
        this.pluginsServer = pluginsServer
        this.db = pluginsServer.db
        this.clickhouse = pluginsServer.clickhouse
        this.kafkaProducer = pluginsServer.kafkaProducer
        this.teamManager = pluginsServer.teamManager
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
        timestamp: DateTime,
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
            // We know `normalizeEvent` has been called here.
            const properties: Properties = data.properties!

            const team = await this.teamManager.fetchTeam(teamId)
            if (!team) {
                throw new Error(`No team found with ID ${teamId}. Can't ingest event.`)
            }

            const personState = new PersonState(
                data,
                teamId,
                distinctId,
                timestamp,
                this.db,
                this.pluginsServer.statsd,
                this.pluginsServer.personManager
            )

            const person = await personState.update()

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
                            timestamp,
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
                        eventUuid,
                        ip,
                        team,
                        data['event'],
                        distinctId,
                        properties,
                        timestamp,
                        person
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

    public clickhouseExternalSchemasEnabled(teamId: number): boolean {
        if (this.pluginsServer.CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS) {
            return false
        }
        return !this.clickhouseExternalSchemasDisabledTeams.has(teamId)
    }

    private async capture(
        eventUuid: string,
        ip: string | null,
        team: Team,
        event: string,
        distinctId: string,
        properties: Properties,
        timestamp: DateTime,
        person: Person | undefined
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

        await this.teamManager.updateEventNamesAndProperties(team.id, event, properties)
        properties = await addGroupProperties(team.id, properties, this.groupTypeManager)

        if (event === '$groupidentify') {
            await this.upsertGroup(team.id, properties, timestamp)
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
            person,
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

    async createEvent(preIngestionEvent: PreIngestionEvent): Promise<IngestionEvent> {
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

        const groupProperties = await this.db.getGroupProperties(teamId, this.getGroupIdentifiers(properties))

        let eventPersonUuid: string | null = null
        let eventPersonProperties: string | null = null
        let personInfo = preIngestionEvent.person

        if (personInfo) {
            eventPersonUuid = personInfo.uuid
            eventPersonProperties = JSON.stringify(personInfo.properties)
        } else {
            personInfo = await this.db.getPersonData(teamId, distinctId)
            if (personInfo) {
                // For consistency, we'd like events to contain the properties that they set, even if those were changed
                // before the event is ingested. Thus we fetch the updated properties but override the values with the event's
                // $set properties if they exist.
                const latestPersonProperties = personInfo ? personInfo?.properties : {}
                eventPersonProperties = JSON.stringify({ ...latestPersonProperties, ...(properties.$set || {}) })
            }
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

        const useExternalSchemas = this.clickhouseExternalSchemasEnabled(teamId)
        // proto ingestion is deprecated and we won't support new additions to the schema
        const message = useExternalSchemas
            ? (EventProto.encodeDelimited(EventProto.create(eventPayload)).finish() as Buffer)
            : Buffer.from(
                  JSON.stringify({
                      ...eventPayload,
                      person_id: eventPersonUuid,
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

        return { ...preIngestionEvent, person: personInfo }
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
        ip: string | null
    ): Promise<PreIngestionEvent> {
        const timestampString = castTimestampOrNow(
            timestamp,
            this.kafkaProducer ? TimestampFormat.ClickHouse : TimestampFormat.ISO
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

import ClickHouse from '@posthog/clickhouse'
import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'

import {
    Element,
    GroupTypeIndex,
    Hub,
    IngestionPersonData,
    ISOTimestamp,
    PerformanceEventReverseMapping,
    PostIngestionEvent,
    PreIngestionEvent,
    RawClickHouseEvent,
    RawPerformanceEvent,
    RawSessionRecordingEvent,
    Team,
    TimestampFormat,
} from '../../types'
import { DB, GroupId } from '../../utils/db/db'
import { elementsToString, extractElements } from '../../utils/db/elements-chain'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import { safeClickhouseString, sanitizeEventName, timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { castTimestampOrNow, UUID } from '../../utils/utils'
import { GroupTypeManager } from './group-type-manager'
import { addGroupProperties } from './groups'
import { LazyPersonContainer } from './lazy-person-container'
import { upsertGroup } from './properties-updater'
import { PropertyDefinitionsManager } from './property-definitions-manager'
import { TeamManager } from './team-manager'
import { captureIngestionWarning } from './utils'

export class EventsProcessor {
    pluginsServer: Hub
    db: DB
    clickhouse: ClickHouse
    kafkaProducer: KafkaProducerWrapper
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    propertyDefinitionsManager: PropertyDefinitionsManager

    constructor(pluginsServer: Hub) {
        this.pluginsServer = pluginsServer
        this.db = pluginsServer.db
        this.clickhouse = pluginsServer.clickhouse
        this.kafkaProducer = pluginsServer.kafkaProducer
        this.teamManager = pluginsServer.teamManager
        this.groupTypeManager = new GroupTypeManager(pluginsServer.db, this.teamManager, pluginsServer.SITE_URL)
        this.propertyDefinitionsManager = new PropertyDefinitionsManager(
            this.teamManager,
            this.groupTypeManager,
            pluginsServer.db,
            pluginsServer,
            pluginsServer.statsd
        )
    }

    public async processEvent(
        distinctId: string,
        ip: string | null,
        data: PluginEvent,
        teamId: number,
        timestamp: DateTime,
        eventUuid: string
    ): Promise<PreIngestionEvent> {
        if (!UUID.validateString(eventUuid, false)) {
            captureIngestionWarning(this.db, teamId, 'skipping_event_invalid_uuid', {
                eventUuid: JSON.stringify(eventUuid),
            })
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

            const captureTimeout = timeoutGuard('Still running "capture". Timeout warning after 30 sec!', {
                eventUuid,
            })
            try {
                result = await this.capture(eventUuid, ip, team, data['event'], distinctId, properties, timestamp)
                this.pluginsServer.statsd?.timing('kafka_queue.single_save.standard', singleSaveTimer, {
                    team_id: teamId.toString(),
                })
            } finally {
                clearTimeout(captureTimeout)
            }
        } finally {
            clearTimeout(timeout)
        }
        return result
    }

    private async capture(
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
            elementsList = extractElements(elements)
            delete properties['$elements']
        }

        if (ip && !team.anonymize_ips && !('$ip' in properties)) {
            properties['$ip'] = ip
        }

        try {
            await this.propertyDefinitionsManager.updateEventNamesAndProperties(team.id, event, properties)
        } catch (err) {
            Sentry.captureException(err)
            status.warn('⚠️', 'Failed to update property definitions for an event', {
                event,
                properties,
                err,
            })
        }
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
            timestamp: timestamp.toISO() as ISOTimestamp,
            elementsList,
            teamId: team.id,
        }
    }

    getGroupIdentifiers(properties: Properties): GroupId[] {
        const res: GroupId[] = []
        for (let groupTypeIndex = 0; groupTypeIndex < this.db.MAX_GROUP_TYPES_PER_TEAM; ++groupTypeIndex) {
            const key = `$group_${groupTypeIndex}`
            if (key in properties) {
                res.push([groupTypeIndex as GroupTypeIndex, properties[key]])
            }
        }
        return res
    }

    async createEvent(
        preIngestionEvent: PreIngestionEvent,
        personContainer: LazyPersonContainer
    ): Promise<PostIngestionEvent> {
        const {
            eventUuid: uuid,
            event,
            teamId,
            distinctId,
            properties,
            timestamp,
            elementsList: elements,
        } = preIngestionEvent

        const elementsChain = elements && elements.length ? elementsToString(elements) : ''

        const groupIdentifiers = this.getGroupIdentifiers(properties)
        const groupsColumns = await this.db.getGroupsColumns(teamId, groupIdentifiers)

        let eventPersonProperties: string | null = null
        let personInfo: IngestionPersonData | undefined = await personContainer.get()

        if (personInfo) {
            eventPersonProperties = JSON.stringify({
                ...personInfo.properties,
                // For consistency, we'd like events to contain the properties that they set, even if those were changed
                // before the event is ingested.
                ...(properties.$set || {}),
            })
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

        const rawEvent: RawClickHouseEvent = {
            uuid,
            event: safeClickhouseString(event),
            properties: JSON.stringify(properties ?? {}),
            timestamp: castTimestampOrNow(timestamp, TimestampFormat.ClickHouse),
            team_id: teamId,
            distinct_id: safeClickhouseString(distinctId),
            elements_chain: safeClickhouseString(elementsChain),
            created_at: castTimestampOrNow(null, TimestampFormat.ClickHouse),
            person_id: personInfo?.uuid,
            person_properties: eventPersonProperties ?? undefined,
            person_created_at: personInfo
                ? castTimestampOrNow(personInfo?.created_at, TimestampFormat.ClickHouseSecondPrecision)
                : undefined,
            ...groupsColumns,
        }

        await this.kafkaProducer.queueMessage({
            topic: this.pluginsServer.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
            messages: [
                {
                    key: uuid,
                    value: JSON.stringify(rawEvent),
                },
            ],
        })

        return preIngestionEvent
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

export const createSessionRecordingEvent = (
    uuid: string,
    team_id: number,
    distinct_id: string,
    timestamp: DateTime,
    ip: string | null,
    properties: Properties
) => {
    const timestampString = castTimestampOrNow(timestamp, TimestampFormat.ClickHouse)

    const data: Partial<RawSessionRecordingEvent> = {
        uuid,
        team_id: team_id,
        distinct_id: distinct_id,
        session_id: properties['$session_id'],
        window_id: properties['$window_id'],
        snapshot_data: JSON.stringify(properties['$snapshot_data']),
        timestamp: timestampString,
        created_at: timestampString,
    }

    return data
}
export function createPerformanceEvent(uuid: string, team_id: number, distinct_id: string, properties: Properties) {
    const data: Partial<RawPerformanceEvent> = {
        uuid,
        team_id: team_id,
        distinct_id: distinct_id,
        session_id: properties['$session_id'],
        window_id: properties['$window_id'],
        pageview_id: properties['$pageview_id'],
        current_url: properties['$current_url'],
    }

    Object.entries(PerformanceEventReverseMapping).forEach(([key, value]) => {
        if (key in properties) {
            data[value] = properties[key]
        }
    })

    return data
}

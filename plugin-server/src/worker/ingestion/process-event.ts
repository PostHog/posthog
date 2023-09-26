import ClickHouse from '@posthog/clickhouse'
import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'

import { activeMilliseconds } from '../../main/ingestion-queues/session-recording/snapshot-segmenter'
import {
    Element,
    GroupTypeIndex,
    Hub,
    ISOTimestamp,
    PerformanceEventReverseMapping,
    Person,
    PreIngestionEvent,
    RawClickHouseEvent,
    RawPerformanceEvent,
    RawSessionRecordingEvent,
    RRWebEvent,
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

        if (ip) {
            if (team.anonymize_ips) {
                ip = null
                delete properties['$ip']
            } else if (!('$ip' in properties)) {
                properties['$ip'] = ip
            }
        }

        try {
            await this.propertyDefinitionsManager.updateEventNamesAndProperties(team.id, event, properties)
        } catch (err) {
            Sentry.captureException(err, { tags: { team_id: team.id } })
            status.warn('⚠️', 'Failed to update property definitions for an event', {
                event,
                properties,
                err,
            })
        }
        // Adds group_0 etc values to properties
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
        person: Person
    ): Promise<[RawClickHouseEvent, Promise<void>]> {
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

        const eventPersonProperties: string = JSON.stringify({
            ...person.properties,
            // For consistency, we'd like events to contain the properties that they set, even if those were changed
            // before the event is ingested.
            ...(properties.$set || {}),
        })
        // TODO: Remove Redis caching for person that's not used anymore

        const rawEvent: RawClickHouseEvent = {
            uuid,
            event: safeClickhouseString(event),
            properties: JSON.stringify(properties ?? {}),
            timestamp: castTimestampOrNow(timestamp, TimestampFormat.ClickHouse),
            team_id: teamId,
            distinct_id: safeClickhouseString(distinctId),
            elements_chain: safeClickhouseString(elementsChain),
            created_at: castTimestampOrNow(null, TimestampFormat.ClickHouse),
            person_id: person.uuid,
            person_properties: eventPersonProperties ?? undefined,
            person_created_at: castTimestampOrNow(person.created_at, TimestampFormat.ClickHouseSecondPrecision),
            ...groupsColumns,
        }

        const ack = this.kafkaProducer.produce({
            topic: this.pluginsServer.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
            key: uuid,
            value: Buffer.from(JSON.stringify(rawEvent)),
            waitForAck: true,
        })

        return [rawEvent, ack]
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

export interface SummarizedSessionRecordingEvent {
    uuid: string
    first_timestamp: string
    last_timestamp: string
    team_id: number
    distinct_id: string
    session_id: string
    first_url: string | null
    click_count: number
    keypress_count: number
    mouse_activity_count: number
    active_milliseconds: number
    console_log_count: number
    console_warn_count: number
    console_error_count: number
    size: number
    event_count: number
    message_count: number
}

export const createSessionReplayEvent = (
    uuid: string,
    team_id: number,
    distinct_id: string,
    session_id: string,
    events: RRWebEvent[]
) => {
    const timestamps = events
        .filter((e) => !!e?.timestamp)
        .map((e) => castTimestampOrNow(DateTime.fromMillis(e.timestamp), TimestampFormat.ClickHouse))
        .sort()

    // but every event where chunk index = 0 must have an eventsSummary
    if (events.length === 0 || timestamps.length === 0) {
        status.warn('🙈', 'ignoring an empty session recording event', {
            session_id,
            events,
        })
        // it is safe to throw here as it caught a level up so that we can see this happening in Sentry
        throw new Error('ignoring an empty session recording event')
    }

    let clickCount = 0
    let keypressCount = 0
    let mouseActivity = 0
    let consoleLogCount = 0
    let consoleWarnCount = 0
    let consoleErrorCount = 0
    let url: string | null = null
    events.forEach((event) => {
        if (event.type === 3) {
            mouseActivity += 1
            if (event.data?.source === 2) {
                clickCount += 1
            }
            if (event.data?.source === 5) {
                keypressCount += 1
            }
        }
        if (url === null && !!event.data?.href?.trim().length) {
            url = event.data.href
        }
        if (event.type === 6 && event.data?.plugin === 'rrweb/console@1') {
            const level = event.data.payload?.level
            if (level === 'log') {
                consoleLogCount += 1
            } else if (level === 'warn') {
                consoleWarnCount += 1
            } else if (level === 'error') {
                consoleErrorCount += 1
            }
        }
    })

    const activeTime = activeMilliseconds(events)

    // NB forces types to be correct e.g. by truncating or rounding
    // to ensure we don't send floats when we should send an integer
    const data: SummarizedSessionRecordingEvent = {
        uuid,
        team_id: team_id,
        distinct_id: String(distinct_id),
        session_id: session_id,
        first_timestamp: timestamps[0],
        last_timestamp: timestamps[timestamps.length - 1],
        click_count: Math.trunc(clickCount),
        keypress_count: Math.trunc(keypressCount),
        mouse_activity_count: Math.trunc(mouseActivity),
        first_url: url,
        active_milliseconds: Math.round(activeTime),
        console_log_count: Math.trunc(consoleLogCount),
        console_warn_count: Math.trunc(consoleWarnCount),
        console_error_count: Math.trunc(consoleErrorCount),
        size: Math.trunc(Buffer.byteLength(JSON.stringify(events), 'utf8')),
        event_count: Math.trunc(events.length),
        message_count: 1,
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

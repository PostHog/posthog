import ClickHouse from '@posthog/clickhouse'
import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { captureException } from '@sentry/node'
import { DateTime } from 'luxon'
import { Counter, Summary } from 'prom-client'

import { activeMilliseconds } from '../../main/ingestion-queues/session-recording/snapshot-segmenter'
import {
    ClickHouseTimestamp,
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
import { MessageSizeTooLarge } from '../../utils/db/error'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import { safeClickhouseString, sanitizeEventName, timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { MessageSizeTooLargeWarningLimiter } from '../../utils/token-bucket'
import { castTimestampOrNow } from '../../utils/utils'
import { GroupTypeManager } from './group-type-manager'
import { addGroupProperties } from './groups'
import { upsertGroup } from './properties-updater'
import { PropertyDefinitionsManager } from './property-definitions-manager'
import { TeamManager } from './team-manager'
import { captureIngestionWarning } from './utils'

const processEventMsSummary = new Summary({
    name: 'process_event_ms',
    help: 'Duration spent in processEvent',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

const elementsOrElementsChainCounter = new Counter({
    name: 'events_pipeline_elements_or_elements_chain_total',
    help: 'Number of times elements or elements_chain appears on event',
    labelNames: ['type'],
})

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
            pluginsServer
        )
    }

    public async processEvent(
        distinctId: string,
        data: PluginEvent,
        teamId: number,
        timestamp: DateTime,
        eventUuid: string
    ): Promise<PreIngestionEvent> {
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
                result = await this.capture(eventUuid, team, data['event'], distinctId, properties, timestamp)
                processEventMsSummary.observe(Date.now() - singleSaveTimer.valueOf())
            } finally {
                clearTimeout(captureTimeout)
            }
        } finally {
            clearTimeout(timeout)
        }
        return result
    }

    private getElementsChain(properties: Properties): string {
        /*
        We're deprecating $elements in favor of $elements_chain, which doesn't require extra
        processing on the ingestion side and is the way we store elements in ClickHouse.
        As part of that we'll move posthog-js to send us $elements_chain as string directly,
        but we still need to support the old way of sending $elements and converting them
        to $elements_chain, while everyone hasn't upgraded.
        */
        let elementsChain = ''
        if (properties['$elements_chain']) {
            elementsChain = properties['$elements_chain']
            elementsOrElementsChainCounter.labels('elements_chain').inc()
        } else if (properties['$elements']) {
            const elements: Record<string, any>[] | undefined = properties['$elements']
            let elementsList: Element[] = []
            if (elements && elements.length) {
                elementsList = extractElements(elements)
                elementsChain = elementsToString(elementsList)
            }
            elementsOrElementsChainCounter.labels('elements').inc()
        }
        delete properties['$elements_chain']
        delete properties['$elements']
        return elementsChain
    }

    private async capture(
        eventUuid: string,
        team: Team,
        event: string,
        distinctId: string,
        properties: Properties,
        timestamp: DateTime
    ): Promise<PreIngestionEvent> {
        event = sanitizeEventName(event)

        if (properties['$ip'] && team.anonymize_ips) {
            delete properties['$ip']
        }

        if (this.pluginsServer.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP === false) {
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
        }

        // Adds group_0 etc values to properties
        properties = await addGroupProperties(team.id, properties, this.groupTypeManager)

        if (event === '$groupidentify') {
            await this.upsertGroup(team.id, properties, timestamp)
        }

        return {
            eventUuid,
            event,
            distinctId,
            properties,
            timestamp: timestamp.toISO() as ISOTimestamp,
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
        const { eventUuid: uuid, event, teamId, distinctId, properties, timestamp } = preIngestionEvent

        let elementsChain = ''
        try {
            elementsChain = this.getElementsChain(properties)
        } catch (error) {
            Sentry.captureException(error, { tags: { team_id: teamId } })
            status.warn('⚠️', 'Failed to process elements', {
                uuid,
                teamId: teamId,
                properties,
                error,
            })
        }

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

        const ack = this.kafkaProducer
            .produce({
                topic: this.pluginsServer.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                key: uuid,
                value: Buffer.from(JSON.stringify(rawEvent)),
                waitForAck: true,
            })
            .catch(async (error) => {
                // Some messages end up significantly larger than the original
                // after plugin processing, person & group enrichment, etc.
                if (error instanceof MessageSizeTooLarge) {
                    if (MessageSizeTooLargeWarningLimiter.consume(`${teamId}`, 1)) {
                        await captureIngestionWarning(this.db, teamId, 'message_size_too_large', {
                            eventUuid: uuid,
                            distinctId: distinctId,
                        })
                    }
                } else {
                    throw error
                }
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
    snapshot_source: string | null
}

export type ConsoleLogEntry = {
    team_id: number
    message: string
    log_level: 'info' | 'warn' | 'error'
    log_source: 'session_replay'
    // the session_id
    log_source_id: string
    // The ClickHouse log_entries table collapses input based on its order by key
    // team_id, log_source, log_source_id, instance_id, timestamp
    // since we don't have a natural instance id, we don't send one.
    // This means that if we can log two messages for one session with the same timestamp
    // we might lose one of them
    // in practice console log timestamps are pretty precise: 2023-10-04 07:53:29.586
    // so, this is unlikely enough that we can avoid filling the DB with UUIDs only to avoid losing
    // a very, very small proportion of console logs.
    instance_id: string | null
    timestamp: ClickHouseTimestamp
}

function sanitizeForUTF8(input: string): string {
    // the JS console truncates some logs...
    // when it does that it doesn't check if the output is valid UTF-8
    // and so it can truncate half way through a UTF-16 pair 🤷
    // the simplest way to fix this is to convert to a buffer and back
    // annoyingly Node 20 has `toWellFormed` which might have been useful
    const buffer = Buffer.from(input)
    return buffer.toString()
}

function safeString(payload: (string | null)[]) {
    // the individual strings are sometimes wrapped in quotes... we want to strip those
    return payload
        .filter((item): item is string => !!item && typeof item === 'string')
        .map((item) => sanitizeForUTF8(item.substring(0, 2999)))
        .join(' ')
}

export enum RRWebEventType {
    DomContentLoaded = 0,
    Load = 1,
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
    Custom = 5,
    Plugin = 6,
}

enum RRWebEventSource {
    Mutation = 0,
    MouseMove = 1,
    MouseInteraction = 2,
    Scroll = 3,
    ViewportResize = 4,
    Input = 5,
    TouchMove = 6,
    MediaInteraction = 7,
    StyleSheetRule = 8,
    CanvasMutation = 9,
    Font = 1,
    Log = 1,
    Drag = 1,
    StyleDeclaration = 1,
    Selection = 1,
}
export const gatherConsoleLogEvents = (
    team_id: number,
    session_id: string,
    events: RRWebEvent[]
): ConsoleLogEntry[] => {
    const consoleLogEntries: ConsoleLogEntry[] = []

    events.forEach((event) => {
        // it should be unnecessary to check for truthiness of event here,
        // but we've seen null in production so 🤷
        if (!!event && event.type === RRWebEventType.Plugin && event.data?.plugin === 'rrweb/console@1') {
            try {
                const level = event.data.payload?.level
                const message = safeString(event.data.payload?.payload)
                consoleLogEntries.push({
                    team_id,
                    // TODO when is it not a single item array?
                    message: message,
                    log_level: level,
                    log_source: 'session_replay',
                    log_source_id: session_id,
                    instance_id: null,
                    timestamp: castTimestampOrNow(DateTime.fromMillis(event.timestamp), TimestampFormat.ClickHouse),
                })
            } catch (e) {
                // if we can't process a console log, we don't want to lose the whole shebang
                captureException(e, { extra: { messagePayload: event.data.payload?.payload }, tags: { session_id } })
            }
        }
    })

    return consoleLogEntries
}

export const getTimestampsFrom = (events: RRWebEvent[]): ClickHouseTimestamp[] =>
    events
        // from millis expects a number and handles unexpected input gracefully so we have to do some filtering
        // since we're accepting input over the API and have seen very unexpected values in the past
        // we want to be very careful here before converting to a DateTime
        // TODO we don't really want to support timestamps of 1,
        //  but we don't currently filter out based on date of RRWebEvents being too far in the past
        .filter((e) => (e?.timestamp || -1) > 0)
        .map((e) => DateTime.fromMillis(e.timestamp))
        .filter((e) => e.isValid)
        .map((e) => castTimestampOrNow(e, TimestampFormat.ClickHouse))
        .sort()

export const createSessionReplayEvent = (
    uuid: string,
    team_id: number,
    distinct_id: string,
    session_id: string,
    events: RRWebEvent[],
    snapshot_source: string | null
) => {
    const timestamps = getTimestampsFrom(events)

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
        if (event.type === RRWebEventType.IncrementalSnapshot) {
            mouseActivity += 1
            if (event.data?.source === RRWebEventSource.MouseInteraction) {
                clickCount += 1
            }
            if (event.data?.source === RRWebEventSource.Input) {
                keypressCount += 1
            }
        }
        if (url === null && !!event.data?.href?.trim().length) {
            url = event.data.href
        }
        if (event.type === RRWebEventType.Plugin && event.data?.plugin === 'rrweb/console@1') {
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
        snapshot_source: snapshot_source || 'web',
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

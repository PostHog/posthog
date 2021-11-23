import { CacheExtension, PluginEvent, Properties } from '@posthog/plugin-scaffold'
import { Plugin, PluginMeta } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Client } from 'pg'

import { ClickHouseEvent, Element, Event, TimestampFormat } from '../../../../types'
import { DB } from '../../../../utils/db/db'
import { chainToElements, transformPostgresElementsToEventPayloadFormat } from '../../../../utils/db/utils'
import { castTimestampToClickhouseFormat, UUIDT } from '../../../../utils/utils'

export interface RawElement extends Element {
    $el_text?: string
}
export interface TimestampBoundaries {
    min: Date | null
    max: Date | null
}

export interface ExportEventsJobPayload extends Record<string, any> {
    // The lower bound of the timestamp interval to be processed
    timestampCursor?: number

    // The offset *within* a given timestamp interval
    intraIntervalOffset?: number

    // how many retries a payload has had (max = 15)
    retriesPerformedSoFar: number

    // tells us we're ready to pick up a new interval
    incrementTimestampCursor: boolean

    // used for ensuring only one "export task" is running if the server restarts
    batchId: number
}

export interface HistoricalExportEvent extends PluginEvent {
    properties: Properties // can't be undefined
}

export type ExportHistoricalEventsUpgrade = Plugin<{
    global: {
        pgClient: Client
        eventsToIgnore: Set<string>
        sanitizedTableName: string
        exportHistoricalEvents: (payload: ExportEventsJobPayload) => Promise<void>
        initTimestampsAndCursor: (payload: Record<string, any> | undefined) => Promise<void>
        setTimestampBoundaries: () => Promise<void>
        updateProgressBar: (incrementedCursor: number) => void
        timestampBoundariesForTeam: TimestampBoundaries
        maxTimestamp: number | null
        minTimestamp: number | null
    }
}>

export const clickhouseEventTimestampToDate = (timestamp: string): Date => {
    return new Date(DateTime.fromFormat(timestamp, 'yyyy-MM-dd HH:mm:ss').toISO())
}

export const fetchTimestampBoundariesForTeam = async (db: DB, teamId: number): Promise<TimestampBoundaries> => {
    if (db.kafkaProducer) {
        const clickhouseFetchTimestampsResult = await db.clickhouseQuery(`
            SELECT min(_timestamp) as min, max(_timestamp) as max
            FROM events
            WHERE team_id = ${teamId}`)
        const min = clickhouseFetchTimestampsResult.data[0].min
        const max = clickhouseFetchTimestampsResult.data[0].max

        const minDate = new Date(clickhouseEventTimestampToDate(min))
        const maxDate = new Date(clickhouseEventTimestampToDate(max))

        const isValidMin = minDate.getTime() !== new Date(0).getTime()
        const isValidMax = maxDate.getTime() !== new Date(0).getTime()

        return {
            min: isValidMin ? minDate : null,
            max: isValidMax ? maxDate : null,
        }
    } else {
        const postgresFetchTimestampsResult = await db.postgresQuery(
            `SELECT min(timestamp), max(timestamp) FROM posthog_event WHERE team_id = $1`,
            [teamId],
            'fetchTimestampBoundariesForTeam'
        )

        const min = postgresFetchTimestampsResult.rows[0].min
        const max = postgresFetchTimestampsResult.rows[0].max
        return {
            min: min ? new Date(min) : null,
            max: max ? new Date(max) : null,
        }
    }
}

export const fetchEventsForInterval = async (
    db: DB,
    teamId: number,
    timestampLowerBound: Date,
    offset: number,
    eventsTimeInterval: number,
    eventsPerRun: number
): Promise<HistoricalExportEvent[]> => {
    const timestampUpperBound = new Date(timestampLowerBound.getTime() + eventsTimeInterval)

    if (db.kafkaProducer) {
        const chTimestampLower = castTimestampToClickhouseFormat(
            DateTime.fromISO(timestampLowerBound.toISOString()),
            TimestampFormat.ClickHouseSecondPrecision
        )
        const chTimestampHigher = castTimestampToClickhouseFormat(
            DateTime.fromISO(timestampUpperBound.toISOString()),
            TimestampFormat.ClickHouseSecondPrecision
        )

        const fetchEventsQuery = `
        SELECT * FROM events 
        WHERE team_id = ${teamId} 
        AND _timestamp >= '${chTimestampLower}' 
        AND _timestamp < '${chTimestampHigher}'
        ORDER BY _offset 
        LIMIT ${eventsPerRun} 
        OFFSET ${offset}`

        const clickhouseFetchEventsResult = await db.clickhouseQuery(fetchEventsQuery)

        return clickhouseFetchEventsResult.data.map((event) =>
            convertClickhouseEventToPluginEvent({
                ...(event as ClickHouseEvent),
                properties: JSON.parse(event.properties || '{}'),
            })
        )
    } else {
        const postgresFetchEventsResult = await db.postgresQuery(
            `SELECT * FROM posthog_event WHERE team_id = $1 AND timestamp >= $2 AND timestamp < $3 ORDER BY id LIMIT $4 OFFSET $5`,
            [teamId, timestampLowerBound.toISOString(), timestampUpperBound.toISOString(), eventsPerRun, offset],
            'fetchEventsForInterval'
        )

        const events = await Promise.all(
            postgresFetchEventsResult.rows.map((event) => convertPostgresEventToPluginEvent(db, event))
        )
        return events
    }
}

export const convertClickhouseEventToPluginEvent = (event: ClickHouseEvent): HistoricalExportEvent => {
    const { event: eventName, properties, timestamp, team_id, distinct_id, created_at, uuid, elements_chain } = event
    if (eventName === '$autocapture' && elements_chain) {
        properties['$elements'] = convertDatabaseElementsToRawElements(chainToElements(elements_chain))
    }
    properties['$$historical_export_source_db'] = 'clickhouse'
    const parsedEvent = {
        uuid,
        team_id,
        distinct_id,
        properties,
        timestamp,
        now: DateTime.now().toISO(),
        event: eventName || '',
        ip: properties?.['$ip'] || '',
        site_url: '',
        sent_at: created_at,
    }
    return addHistoricalExportEventProperties(parsedEvent)
}

export const convertPostgresEventToPluginEvent = async (db: DB, event: Event): Promise<HistoricalExportEvent> => {
    const {
        event: eventName,
        timestamp,
        team_id,
        distinct_id,
        created_at,
        properties,
        elements,
        id,
        elements_hash,
    } = event
    properties['$$postgres_event_id'] = id
    if (eventName === '$autocapture') {
        if (elements && elements.length > 0) {
            properties['$elements'] = convertDatabaseElementsToRawElements(elements)
        } else {
            const dbElements = await db.fetchPostgresElementsByHash(team_id, elements_hash)
            properties['$elements'] = transformPostgresElementsToEventPayloadFormat(dbElements)
        }
    }

    properties['$$historical_export_source_db'] = 'postgres'
    const parsedEvent = {
        uuid: new UUIDT().toString(), // postgres events don't store a uuid
        team_id,
        distinct_id,
        properties,
        timestamp,
        now: DateTime.now().toISO(),
        event: eventName || '',
        ip: properties?.['$ip'] || '',
        site_url: '',
        sent_at: created_at,
    }
    return addHistoricalExportEventProperties(parsedEvent)
}

const addHistoricalExportEventProperties = (event: HistoricalExportEvent): HistoricalExportEvent => {
    event.properties['$$is_historical_export_event'] = true
    event.properties['$$historical_export_timestamp'] = new Date().toISOString()
    return event
}

const convertDatabaseElementsToRawElements = (elements: RawElement[]): RawElement[] => {
    for (const element of elements) {
        if (element.attributes && element.attributes.attr__class) {
            element.attr_class = element.attributes.attr__class
        }
        if (element.text) {
            element.$el_text = element.text
        }
    }
    return elements
}

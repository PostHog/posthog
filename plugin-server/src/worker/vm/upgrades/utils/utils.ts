import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import { Plugin } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'
import { Client } from 'pg'

import { Element, Event, TimestampFormat } from '../../../../types'
import { DB } from '../../../../utils/db/db'
import { castTimestampToClickhouseFormat } from '../../../../utils/utils'

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
    try {
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
    } catch (e) {
        Sentry.captureException(e)
        return {
            min: null,
            max: null,
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

    const chTimestampLower = castTimestampToClickhouseFormat(
        DateTime.fromISO(timestampLowerBound.toISOString()),
        TimestampFormat.ClickHouseSecondPrecision
    )
    const chTimestampHigher = castTimestampToClickhouseFormat(
        DateTime.fromISO(timestampUpperBound.toISOString()),
        TimestampFormat.ClickHouseSecondPrecision
    )

    const fetchEventsQuery = `
    SELECT
        event,
        uuid,
        team_id,
        distinct_id,
        properties,
        timestamp,
        created_at,
        elements_chain
    FROM events
    WHERE team_id = ${teamId}
    AND timestamp >= '${chTimestampLower}'
    AND timestamp < '${chTimestampHigher}'
    ORDER BY timestamp
    LIMIT ${eventsPerRun}
    OFFSET ${offset}`

    const clickhouseFetchEventsResult = await db.clickhouseQuery(fetchEventsQuery)

    return clickhouseFetchEventsResult.data.map((event) =>
        convertClickhouseEventToPluginEvent({
            ...(event as Event),
            properties: JSON.parse(event.properties || '{}'),
        })
    )
}

export const convertClickhouseEventToPluginEvent = (event: Event): HistoricalExportEvent => {
    const { event: eventName, properties, timestamp, team_id, distinct_id, created_at, uuid, elements_chain } = event
    if (eventName === '$autocapture' && elements_chain) {
        properties['$elements'] = convertDatabaseElementsToRawElements(elements_chain)
    }
    properties['$$historical_export_source_db'] = 'clickhouse'
    const parsedEvent = {
        uuid,
        team_id,
        distinct_id,
        properties,
        timestamp: timestamp.toISO(),
        now: DateTime.now().toISO(),
        event: eventName || '',
        ip: properties?.['$ip'] || '',
        site_url: '',
        sent_at: created_at.toISO(),
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

import { CacheExtension, PluginEvent } from '@posthog/plugin-scaffold'
import { Plugin, PluginMeta } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Client } from 'pg'

import { ClickHouseEvent, Event, PluginConfig, TimestampFormat } from '../../../../types'
import { DB } from '../../../../utils/db/db'
import { castTimestampToClickhouseFormat } from '../../../../utils/utils'
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
}

export type ExportEventsFromTheBeginningUpgrade = Plugin<{
    global: {
        pgClient: Client
        eventsToIgnore: Set<string>
        sanitizedTableName: string
        exportEventsFromTheBeginning: (payload: ExportEventsJobPayload) => Promise<void>
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
): Promise<PluginEvent[]> => {
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
            convertDatabaseEventToPluginEvent({
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

        return postgresFetchEventsResult.rows.map(convertDatabaseEventToPluginEvent)
    }
}

export const convertDatabaseEventToPluginEvent = (
    event: Omit<Event, 'id' | 'elements' | 'elements_hash'>
): PluginEvent => {
    const { event: eventName, properties, timestamp, team_id, distinct_id, created_at } = event
    return {
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
}

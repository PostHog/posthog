import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import { Plugin } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'
import { Client } from 'pg'

import { DB } from '../../../../utils/db/db'

export interface TimestampBoundaries {
    min: Date
    max: Date
}

export interface ExportHistoricalEventsJobPayload extends Record<string, any> {
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
        exportHistoricalEvents: (payload: ExportHistoricalEventsJobPayload) => Promise<void>
        initTimestampsAndCursor: (payload: ExportHistoricalEventsJobPayload | undefined) => Promise<void>
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

export const fetchTimestampBoundariesForTeam = async (
    db: DB,
    teamId: number,
    column: 'timestamp' | '_timestamp'
): Promise<TimestampBoundaries | null> => {
    try {
        const clickhouseFetchTimestampsResult = await db.clickhouseQuery(`
        /* plugin-server:fetchTimestampBoundariesForTeam */
        SELECT min(${column}) as min, max(${column}) as max
        FROM events
        WHERE team_id = ${teamId}`)

        const min = clickhouseFetchTimestampsResult.data[0].min
        const max = clickhouseFetchTimestampsResult.data[0].max

        const minDate = new Date(clickhouseEventTimestampToDate(min))
        const maxDate = new Date(clickhouseEventTimestampToDate(max))

        const isValidMin = minDate.getTime() !== new Date(0).getTime()
        const isValidMax = maxDate.getTime() !== new Date(0).getTime()

        return isValidMin && isValidMax ? { min: minDate, max: maxDate } : null
    } catch (e) {
        Sentry.captureException(e)
        return null
    }
}

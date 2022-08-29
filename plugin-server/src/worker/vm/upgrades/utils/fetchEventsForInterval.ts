import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'

import { ClickHouseEvent, Element, TimestampFormat } from '../../../../types'
import { DB } from '../../../../utils/db/db'
import { castTimestampToClickhouseFormat } from '../../../../utils/utils'
import { HistoricalExportEvent } from './utils'

export interface RawElement extends Element {
    $el_text?: string
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
            ...(event as ClickHouseEvent),
            properties: JSON.parse(event.properties || '{}'),
        })
    )
}

const convertClickhouseEventToPluginEvent = (event: ClickHouseEvent): HistoricalExportEvent => {
    const { event: eventName, properties, timestamp, team_id, distinct_id, created_at, uuid, elements_chain } = event
    if (eventName === '$autocapture' && elements_chain) {
        properties['$elements'] = convertDatabaseElementsToRawElements(elements_chain)
    }
    properties['$$historical_export_source_db'] = 'clickhouse'
    let ts: DateTime | string = timestamp
    try {
        ts = timestamp.toISO()
    } catch (e) {
        Sentry.captureException(e, { extra: { event, timestamp } })
    }
    const parsedEvent = {
        uuid,
        team_id,
        distinct_id,
        properties,
        timestamp: String(ts),
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

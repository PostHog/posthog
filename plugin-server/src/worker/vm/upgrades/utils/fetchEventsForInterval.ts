import { DateTime } from 'luxon'

import { Element, RawClickHouseEvent, TimestampFormat } from '../../../../types'
import { DB } from '../../../../utils/db/db'
import { parseRawClickHouseEvent } from '../../../../utils/event'
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

    // :TODO: Adding tag messes up the return value?
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

    const clickhouseFetchEventsResult = await db.clickhouseQuery<RawClickHouseEvent>(fetchEventsQuery)

    return clickhouseFetchEventsResult.data.map(convertClickhouseEventToPluginEvent)
}

const convertClickhouseEventToPluginEvent = (event: RawClickHouseEvent): HistoricalExportEvent => {
    const clickhouseEvent = parseRawClickHouseEvent(event)
    if (clickhouseEvent.event === '$autocapture' && clickhouseEvent.elements_chain) {
        clickhouseEvent.properties['$elements'] = convertDatabaseElementsToRawElements(clickhouseEvent.elements_chain)
    }
    const parsedEvent = {
        uuid: clickhouseEvent.uuid,
        team_id: clickhouseEvent.team_id,
        distinct_id: clickhouseEvent.distinct_id,
        properties: clickhouseEvent.properties,
        timestamp: clickhouseEvent.timestamp.toISO(),
        now: DateTime.now().toISO(),
        event: event.event || '',
        ip: clickhouseEvent.properties['$ip'] || '',
        site_url: '',
        sent_at: clickhouseEvent.created_at.toISO(),
    }
    return addHistoricalExportEventProperties(parsedEvent)
}

const addHistoricalExportEventProperties = (event: HistoricalExportEvent): HistoricalExportEvent => {
    event.properties['$$historical_export_source_db'] = 'clickhouse'
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

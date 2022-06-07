import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { ClickhouseEventKafka, IngestionEvent } from '../types'
import { chainToElements } from './db/utils'
import { clickHouseTimestampToISO } from './utils'

export function convertToProcessedPluginEvent(event: IngestionEvent): ProcessedPluginEvent {
    const timestamp = typeof event.timestamp === 'string' ? event.timestamp : event.timestamp.toUTC().toISO()

    return {
        distinct_id: event.distinctId,
        ip: event.ip,
        team_id: event.teamId,
        event: event.event,
        properties: event.properties,
        timestamp: timestamp,
        $set: event.properties.$set,
        $set_once: event.properties.$set_once,
        uuid: event.eventUuid,
    }
}

export function convertToIngestionEvent(event: ClickhouseEventKafka): IngestionEvent {
    const properties = JSON.parse(event.properties)
    return {
        eventUuid: event.uuid,
        event: event.event!,
        ip: properties['$ip'],
        teamId: event.team_id,
        distinctId: event.distinct_id,
        properties: properties,
        timestamp: clickHouseTimestampToISO(event.timestamp),
        elementsList: event.elements_chain ? chainToElements(event.elements_chain) : [],
    }
}

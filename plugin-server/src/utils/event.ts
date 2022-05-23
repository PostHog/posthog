import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { ClickHouseEvent, PreIngestionEvent } from '../types'

export function convertToProcessedPluginEvent(event: PreIngestionEvent): ProcessedPluginEvent {
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

export function convertToPreIngestionEvent(event: ClickHouseEvent): PreIngestionEvent {
    return {
        eventUuid: event.uuid,
        event: event.event!,
        ip: event.properties['$ip'],
        teamId: event.team_id,
        distinctId: event.distinct_id,
        properties: event.properties,
        timestamp: event.timestamp,
        elementsList: [],
    }
}

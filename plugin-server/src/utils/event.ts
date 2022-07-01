import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { ClickhouseEventKafka, Event, IngestionEvent, RawEvent } from '../types'
import { chainToElements } from './db/elements-chain'
import { personInitialAndUTMProperties } from './db/utils'
import { clickHouseTimestampToDateTime, clickHouseTimestampToISO } from './utils'

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

export function normalizeEvent(event: PluginEvent): PluginEvent {
    event.distinct_id = event.distinct_id?.toString()

    let properties = event.properties ?? {}
    if (event['$set']) {
        properties['$set'] = { ...properties['$set'], ...event['$set'] }
    }
    if (event['$set_once']) {
        properties['$set_once'] = { ...properties['$set_once'], ...event['$set_once'] }
    }
    if (event.event !== '$snapshot') {
        properties = personInitialAndUTMProperties(properties)
    }
    event.properties = properties
    return event
}

/** Parse an event row SELECTed from ClickHouse into a more malleable form. */
export function parseEventRow(rawEvent: RawEvent): Event {
    return {
        ...rawEvent,
        timestamp: clickHouseTimestampToDateTime(rawEvent.timestamp),
        created_at: clickHouseTimestampToDateTime(rawEvent.created_at),
        properties: rawEvent.properties ? JSON.parse(rawEvent.properties) : {},
        person_properties: rawEvent.person_properties ? JSON.parse(rawEvent.person_properties) : {},
        group0_properties: rawEvent.group0_properties ? JSON.parse(rawEvent.group0_properties) : {},
        group1_properties: rawEvent.group1_properties ? JSON.parse(rawEvent.group1_properties) : {},
        group2_properties: rawEvent.group2_properties ? JSON.parse(rawEvent.group2_properties) : {},
        group3_properties: rawEvent.group3_properties ? JSON.parse(rawEvent.group3_properties) : {},
        group4_properties: rawEvent.group4_properties ? JSON.parse(rawEvent.group4_properties) : {},
    }
}

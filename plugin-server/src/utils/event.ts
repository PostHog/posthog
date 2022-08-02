import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { KafkaMessage } from 'kafkajs'

import { ClonableIngestionEvent, Event, PostIngestionEvent, RawEvent } from '../types'
import { chainToElements } from './db/elements-chain'
import { personInitialAndUTMProperties } from './db/utils'
import { clickHouseTimestampToDateTime } from './utils'

export function convertToProcessedPluginEvent(
    event: PostIngestionEvent | ClonableIngestionEvent
): ProcessedPluginEvent {
    return {
        distinct_id: event.distinctId,
        ip: event.ip,
        team_id: event.teamId,
        event: event.event,
        properties: event.properties,
        timestamp: typeof event.timestamp === 'string' ? event.timestamp : event.timestamp.toISO(),
        $set: event.properties.$set,
        $set_once: event.properties.$set_once,
        uuid: event.eventUuid,
        elements: event.elementsList,
    }
}

/** Parse an event row SELECTed from ClickHouse into a more malleable form. */
export function convertToParsedEvent(rawEvent: RawEvent): Event {
    return {
        ...rawEvent,
        timestamp: clickHouseTimestampToDateTime(rawEvent.timestamp),
        created_at: clickHouseTimestampToDateTime(rawEvent.created_at),
        properties: rawEvent.properties ? JSON.parse(rawEvent.properties) : {},
        elements_chain: rawEvent.elements_chain ? chainToElements(rawEvent.elements_chain) : null,
        person_created_at: rawEvent.person_created_at
            ? clickHouseTimestampToDateTime(rawEvent.person_created_at)
            : null,
        person_properties: rawEvent.person_properties ? JSON.parse(rawEvent.person_properties) : {},
        group0_properties: rawEvent.group0_properties ? JSON.parse(rawEvent.group0_properties) : {},
        group1_properties: rawEvent.group1_properties ? JSON.parse(rawEvent.group1_properties) : {},
        group2_properties: rawEvent.group2_properties ? JSON.parse(rawEvent.group2_properties) : {},
        group3_properties: rawEvent.group3_properties ? JSON.parse(rawEvent.group3_properties) : {},
        group4_properties: rawEvent.group4_properties ? JSON.parse(rawEvent.group4_properties) : {},
    }
}

export function convertToIngestionEvent(event: RawEvent): PostIngestionEvent {
    const properties = event.properties ? JSON.parse(event.properties) : {}
    return {
        eventUuid: event.uuid,
        event: event.event!,
        ip: properties['$ip'],
        teamId: event.team_id,
        distinctId: event.distinct_id,
        properties,
        timestamp: clickHouseTimestampToDateTime(event.timestamp),
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

export function formPluginEvent(message: KafkaMessage): PluginEvent {
    // TODO: inefficient to do this twice?
    const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
    const combinedEvent = { ...JSON.parse(dataStr), ...rawEvent }
    const event: PluginEvent = normalizeEvent({
        ...combinedEvent,
        site_url: combinedEvent.site_url || null,
        ip: combinedEvent.ip || null,
    })
    return event
}

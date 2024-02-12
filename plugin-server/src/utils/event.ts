import { PluginEvent, PostHogEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { ClickHouseEvent, Element, PipelineEvent, PostIngestionEvent, RawClickHouseEvent } from '../types'
import { chainToElements } from './db/elements-chain'
import { personInitialAndUTMProperties } from './db/utils'
import {
    clickHouseTimestampSecondPrecisionToISO,
    clickHouseTimestampToDateTime,
    clickHouseTimestampToISO,
} from './utils'

interface RawElement extends Element {
    $el_text?: string
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

export function convertToProcessedPluginEvent(event: PostIngestionEvent): ProcessedPluginEvent {
    return {
        distinct_id: event.distinctId,
        ip: null, // deprecated : within properties[$ip] now
        team_id: event.teamId,
        event: event.event,
        properties: event.properties,
        timestamp: event.timestamp,
        $set: event.properties.$set,
        $set_once: event.properties.$set_once,
        uuid: event.eventUuid,
        elements: convertDatabaseElementsToRawElements(event.elementsList ?? []),
    }
}

/** Parse an event row SELECTed from ClickHouse into a more malleable form. */
export function parseRawClickHouseEvent(rawEvent: RawClickHouseEvent): ClickHouseEvent {
    return {
        ...rawEvent,
        timestamp: clickHouseTimestampToDateTime(rawEvent.timestamp),
        created_at: clickHouseTimestampToDateTime(rawEvent.created_at),
        properties: rawEvent.properties ? JSON.parse(rawEvent.properties) : {},
        elements_chain: rawEvent.elements_chain ? chainToElements(rawEvent.elements_chain, rawEvent.team_id) : null,
        person_created_at: rawEvent.person_created_at
            ? clickHouseTimestampToDateTime(rawEvent.person_created_at)
            : null,
        person_properties: rawEvent.person_properties ? JSON.parse(rawEvent.person_properties) : {},
        group0_properties: rawEvent.group0_properties ? JSON.parse(rawEvent.group0_properties) : {},
        group1_properties: rawEvent.group1_properties ? JSON.parse(rawEvent.group1_properties) : {},
        group2_properties: rawEvent.group2_properties ? JSON.parse(rawEvent.group2_properties) : {},
        group3_properties: rawEvent.group3_properties ? JSON.parse(rawEvent.group3_properties) : {},
        group4_properties: rawEvent.group4_properties ? JSON.parse(rawEvent.group4_properties) : {},
        group0_created_at: rawEvent.group0_created_at
            ? clickHouseTimestampToDateTime(rawEvent.group0_created_at)
            : null,
        group1_created_at: rawEvent.group1_created_at
            ? clickHouseTimestampToDateTime(rawEvent.group1_created_at)
            : null,
        group2_created_at: rawEvent.group2_created_at
            ? clickHouseTimestampToDateTime(rawEvent.group2_created_at)
            : null,
        group3_created_at: rawEvent.group3_created_at
            ? clickHouseTimestampToDateTime(rawEvent.group3_created_at)
            : null,
        group4_created_at: rawEvent.group4_created_at
            ? clickHouseTimestampToDateTime(rawEvent.group4_created_at)
            : null,
    }
}
export function convertToPostHogEvent(event: RawClickHouseEvent): PostHogEvent {
    const properties = event.properties ? JSON.parse(event.properties) : {}
    properties['$elements_chain'] = event.elements_chain // TODO: tests
    return {
        uuid: event.uuid,
        event: event.event!,
        team_id: event.team_id,
        distinct_id: event.distinct_id,
        properties,
        timestamp: new Date(clickHouseTimestampToISO(event.timestamp)),
    }
}

export function convertToIngestionEvent(event: RawClickHouseEvent, skipElementsChain = false): PostIngestionEvent {
    const properties = event.properties ? JSON.parse(event.properties) : {}
    return {
        eventUuid: event.uuid,
        event: event.event!,
        teamId: event.team_id,
        distinctId: event.distinct_id,
        properties,
        timestamp: clickHouseTimestampToISO(event.timestamp),
        elementsList: skipElementsChain
            ? []
            : event.elements_chain
            ? chainToElements(event.elements_chain, event.team_id)
            : [],
        person_id: event.person_id,
        person_created_at: event.person_created_at
            ? clickHouseTimestampSecondPrecisionToISO(event.person_created_at)
            : null,
        person_properties: event.person_properties ? JSON.parse(event.person_properties) : {},
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
    if (!properties['$ip'] && event.ip) {
        // if $ip wasn't sent with the event, then add what we got from capture
        properties['$ip'] = event.ip
    }
    // For safety while PluginEvent still has an `ip` field
    event.ip = null

    if (!['$snapshot', '$performance_event'].includes(event.event)) {
        properties = personInitialAndUTMProperties(properties)
    }
    if (event.sent_at) {
        properties['$sent_at'] = event.sent_at
    }

    event.properties = properties
    return event
}

export function formPipelineEvent(message: Message): PipelineEvent {
    // TODO: inefficient to do this twice?
    const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
    const combinedEvent = { ...JSON.parse(dataStr), ...rawEvent }
    const event: PipelineEvent = normalizeEvent({
        ...combinedEvent,
        site_url: combinedEvent.site_url || null,
    })
    return event
}

export function formPluginEvent(event: RawClickHouseEvent): PluginEvent {
    const postIngestionEvent = convertToIngestionEvent(event)
    return {
        distinct_id: postIngestionEvent.distinctId,
        ip: null, // deprecated : within properties[$ip] now
        site_url: '',
        team_id: postIngestionEvent.teamId,
        now: DateTime.now().toISO(),
        event: postIngestionEvent.event,
        properties: postIngestionEvent.properties,
        timestamp: postIngestionEvent.timestamp,
        uuid: postIngestionEvent.eventUuid,
    }
}

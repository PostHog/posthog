import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { KafkaMessage } from 'kafkajs'

import { ClickhouseEventKafka, IngestionEvent } from '../types'
import { chainToElements } from './db/elements-chain'
import { personInitialAndUTMProperties } from './db/utils'
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
        elements: event.elementsList,
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

export function formPluginEvent(message: KafkaMessage): PluginEvent {
    // TODO: inefficient to do this twice?
    const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
    const combinedEvent = { ...rawEvent, ...JSON.parse(dataStr) }
    const event: PluginEvent = normalizeEvent({
        ...combinedEvent,
        site_url: combinedEvent.site_url || null,
        ip: combinedEvent.ip || null,
    })
    return event
}

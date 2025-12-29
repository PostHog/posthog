import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { ClickHouseEvent, PipelineEvent, PostIngestionEvent, RawClickHouseEvent } from '../types'
import { personInitialAndUTMProperties, sanitizeString } from './db/utils'
import { chainToElements } from './elements-chain'
import { parseJSON } from './json-parse'
import { clickHouseTimestampToDateTime } from './utils'

export function convertToOnEventPayload(event: PostIngestionEvent): ProcessedPluginEvent {
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
        elements: event.elementsList ?? [],
    }
}

/** Parse an event row SELECTed from ClickHouse into a more malleable form. */
export function parseRawClickHouseEvent(rawEvent: RawClickHouseEvent): ClickHouseEvent {
    return {
        ...rawEvent,
        timestamp: clickHouseTimestampToDateTime(rawEvent.timestamp),
        created_at: clickHouseTimestampToDateTime(rawEvent.created_at),
        properties: rawEvent.properties ? parseJSON(rawEvent.properties) : {},
        elements_chain: rawEvent.elements_chain ? chainToElements(rawEvent.elements_chain, rawEvent.team_id) : null,
        person_created_at: rawEvent.person_created_at
            ? clickHouseTimestampToDateTime(rawEvent.person_created_at)
            : null,
        person_properties: rawEvent.person_properties ? parseJSON(rawEvent.person_properties) : {},
        group0_properties: rawEvent.group0_properties ? parseJSON(rawEvent.group0_properties) : {},
        group1_properties: rawEvent.group1_properties ? parseJSON(rawEvent.group1_properties) : {},
        group2_properties: rawEvent.group2_properties ? parseJSON(rawEvent.group2_properties) : {},
        group3_properties: rawEvent.group3_properties ? parseJSON(rawEvent.group3_properties) : {},
        group4_properties: rawEvent.group4_properties ? parseJSON(rawEvent.group4_properties) : {},
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

/**
 * Elements parsing can be really slow so it is only done when required by the caller.
 * It mutates the event which is not ideal but the performance gains of lazy loading it were deemed worth it.
 */
export function mutatePostIngestionEventWithElementsList(event: PostIngestionEvent): void {
    if (event.elementsList) {
        // Don't set if already done before
        return
    }

    event.elementsList = event.properties['$elements_chain']
        ? chainToElements(event.properties['$elements_chain'], event.teamId)
        : []

    event.elementsList = event.elementsList.map((element) => ({
        ...element,
        attr_class: element.attributes?.attr__class ?? element.attr_class,
        $el_text: element.text,
    }))
}

/// Does normalization steps involving the $process_person_profile property. This is currently a separate
/// function because `normalizeEvent` is called from multiple places, some early in the pipeline,
/// and we want to have one trusted place where `$process_person_profile` is handled and passed through
/// all of the processing steps.
///
/// If `formPipelineEvent` is removed this can easily be combined with `normalizeEvent`.
export function normalizeProcessPerson<T extends PipelineEvent | PluginEvent>(event: T, processPerson: boolean): T {
    const properties = event.properties ?? {}

    if (!processPerson || event.event === '$groupidentify') {
        delete event.$set
        delete event.$set_once
        // In an abundance of caution and future proofing, we delete the $unset field from the
        // event if it is set. As of this writing we only *read* $unset out of `properties`, but
        // we may as well future-proof this code path.
        delete (event as any)['$unset']
        delete properties.$set
        delete properties.$set_once
        delete properties.$unset
    }

    if (!processPerson) {
        // Recorded for clarity and so that the property exists if it is ever sent elsewhere,
        // e.g. for migrations.
        properties.$process_person_profile = false
    } else {
        // Removed as it is the default, note that we have record the `person_mode` column
        // in ClickHouse for all events.
        delete properties.$process_person_profile
    }

    event.properties = properties
    return event
}

/**
 * Sanitizes event inputs and merges top-level $set/$set_once into properties.
 * Does NOT call personInitialAndUTMProperties - that's done in normalizeEvent
 * which should only be called once after transformations.
 *
 * This split ensures:
 * - Transformations see clean events without pre-computed $set/$set_once from UTM/browser fields
 * - Transformations can add properties that become person properties
 * - personInitialAndUTMProperties runs only once, after transformations
 */
export function sanitizeEvent<T extends PipelineEvent | PluginEvent>(event: T): T {
    event.distinct_id = sanitizeString(String(event.distinct_id))

    if ('token' in event) {
        event.token = sanitizeString(String(event.token))
    }

    const properties = event.properties ?? {}
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

    if (event.sent_at) {
        properties['$sent_at'] = event.sent_at
    }

    event.properties = properties
    return event
}

/**
 * Full event normalization including person property mapping.
 * This should only be called ONCE per event, after any transformations.
 * Calling it multiple times is wasteful as personInitialAndUTMProperties
 * does significant work iterating properties.
 */
export function normalizeEvent<T extends PipelineEvent | PluginEvent>(event: T): T {
    event = sanitizeEvent(event)

    if (!['$snapshot', '$performance_event'].includes(event.event)) {
        event.properties = personInitialAndUTMProperties(event.properties!)
    }

    return event
}

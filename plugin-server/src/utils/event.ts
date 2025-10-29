import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { PluginEvent, PostHogEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { setUsageInNonPersonEventsCounter } from '../main/ingestion-queues/metrics'
import {
    ClickHouseEvent,
    HookPayload,
    PipelineEvent,
    PostIngestionEvent,
    RawClickHouseEvent,
    RawKafkaEvent,
} from '../types'
import { chainToElements } from './db/elements-chain'
import {
    hasDifferenceWithProposedNewNormalisationMode,
    personInitialAndUTMProperties,
    sanitizeString,
} from './db/utils'
import { parseJSON } from './json-parse'
import {
    clickHouseTimestampSecondPrecisionToISO,
    clickHouseTimestampToDateTime,
    clickHouseTimestampToISO,
    getKnownLibValueOrSentinel,
} from './utils'

const PERSON_EVENTS = new Set(['$set', '$identify', '$create_alias', '$merge_dangerously', '$groupidentify'])
const KNOWN_SET_EVENTS = new Set([
    '$feature_interaction',
    '$feature_enrollment_update',
    'survey dismissed',
    'survey sent',
])

const DIFFERENCE_WITH_PROPOSED_NORMALISATION_MODE_COUNTER = new Counter({
    name: 'difference_with_proposed_normalisation_mode',
    help: 'Counter for events that would give a different result with the new proposed normalisation mode',
    labelNames: ['library'],
})

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

export function convertToHookPayload(event: PostIngestionEvent): HookPayload['data'] {
    // It is only at this point that we need the elements list for the full event
    // NOTE: It is possible that nobody uses it in which case we could remove this for performance but
    // currently we have no way of being sure so we keep it in
    mutatePostIngestionEventWithElementsList(event)

    return {
        eventUuid: event.eventUuid,
        event: event.event,
        teamId: event.teamId,
        distinctId: event.distinctId,
        properties: event.properties,
        timestamp: event.timestamp,
        elementsList: event.elementsList,
        person: {
            uuid: event.person_id!,
            properties: event.person_properties,
            created_at: event.person_created_at,
        },
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
export function convertToPostHogEvent(event: PostIngestionEvent): PostHogEvent {
    return {
        uuid: event.eventUuid,
        event: event.event!,
        team_id: event.teamId,
        distinct_id: event.distinctId,
        properties: event.properties,
        timestamp: new Date(event.timestamp),
    }
}

// NOTE: PostIngestionEvent is our context event - it should never be sent directly to an output, but rather transformed into a lightweight schema
// that we can keep to as a contract
export function convertToPostIngestionEvent(event: RawKafkaEvent): PostIngestionEvent {
    const properties = event.properties ? parseJSON(event.properties) : {}
    if (event.elements_chain) {
        properties['$elements_chain'] = event.elements_chain
    }

    return {
        eventUuid: event.uuid,
        event: event.event!,
        teamId: event.team_id,
        projectId: event.project_id,
        distinctId: event.distinct_id,
        properties,
        timestamp: clickHouseTimestampToISO(event.timestamp),
        elementsList: undefined,
        person_id: event.person_id,
        person_created_at: event.person_created_at
            ? clickHouseTimestampSecondPrecisionToISO(event.person_created_at)
            : null,
        person_properties: event.person_properties ? parseJSON(event.person_properties) : {},
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

export function normalizeEvent<T extends PipelineEvent | PluginEvent>(event: T): T {
    event.distinct_id = sanitizeString(String(event.distinct_id))

    if ('token' in event) {
        event.token = sanitizeString(String(event.token))
    }

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

    if (hasDifferenceWithProposedNewNormalisationMode(properties)) {
        DIFFERENCE_WITH_PROPOSED_NORMALISATION_MODE_COUNTER.labels({
            library: getKnownLibValueOrSentinel(properties['$lib']),
        }).inc()
    }

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
    const { data: dataStr, ...rawEvent } = parseJSON(message.value!.toString())
    const combinedEvent: PipelineEvent = { ...parseJSON(dataStr), ...rawEvent }

    // Track $set usage in events that aren't known to use it, before ingestion adds anything there
    if (
        combinedEvent.properties &&
        !PERSON_EVENTS.has(combinedEvent.event) &&
        !KNOWN_SET_EVENTS.has(combinedEvent.event) &&
        ('$set' in combinedEvent.properties ||
            '$set_once' in combinedEvent.properties ||
            '$unset' in combinedEvent.properties)
    ) {
        setUsageInNonPersonEventsCounter.inc()
    }

    const event: PipelineEvent = normalizeEvent({
        ...combinedEvent,
    })
    return event
}

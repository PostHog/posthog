import { PluginEvent, PostHogEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { Message } from 'node-rdkafka'

import {
    ClickHouseEvent,
    GroupTypeToColumnIndex,
    HookPayload,
    PipelineEvent,
    PostIngestionEvent,
    RawClickHouseEvent,
} from '../types'
import { chainToElements } from './db/elements-chain'
import { personInitialAndUTMProperties, sanitizeString } from './db/utils'
import {
    clickHouseTimestampSecondPrecisionToISO,
    clickHouseTimestampToDateTime,
    clickHouseTimestampToISO,
} from './utils'

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
export function convertToPostIngestionEvent(
    event: RawClickHouseEvent,
    groupTypes?: GroupTypeToColumnIndex
): PostIngestionEvent {
    const properties = event.properties ? JSON.parse(event.properties) : {}
    if (event.elements_chain) {
        properties['$elements_chain'] = event.elements_chain
    }

    let groups: PostIngestionEvent['groups'] = undefined

    if (groupTypes) {
        groups = {}

        for (const [groupType, columnIndex] of Object.entries(groupTypes)) {
            const groupKey = (properties[`$groups`] || {})[groupType]
            const groupProperties = event[`group${columnIndex}_properties`]

            // TODO: Check that groupProperties always exist if the event is in that group
            if (groupKey && groupProperties) {
                groups[groupType] = {
                    index: columnIndex,
                    key: groupKey,
                    type: groupType,
                    properties: JSON.parse(groupProperties),
                }
            }
        }
    }

    return {
        eventUuid: event.uuid,
        event: event.event!,
        teamId: event.team_id,
        distinctId: event.distinct_id,
        properties,
        timestamp: clickHouseTimestampToISO(event.timestamp),
        elementsList: undefined,
        person_id: event.person_id,
        person_created_at: event.person_created_at
            ? clickHouseTimestampSecondPrecisionToISO(event.person_created_at)
            : null,
        person_properties: event.person_properties ? JSON.parse(event.person_properties) : {},
        groups,
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
export function normalizeProcessPerson(event: PluginEvent, processPerson: boolean): PluginEvent {
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

export function normalizeEvent(event: PluginEvent): PluginEvent {
    event.distinct_id = sanitizeString(String(event.distinct_id))

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

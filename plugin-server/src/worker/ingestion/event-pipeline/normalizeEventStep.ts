import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { normalizeEvent, normalizeProcessPerson } from '../../../utils/event'
import { status } from '../../../utils/status'
import { parseEventTimestamp } from '../timestamps'
import { captureIngestionWarning } from '../utils'
import { EventPipelineRunner } from './runner'

function isNotNullOrUndefinedOrObject(value: any): boolean {
    return typeof value !== 'undefined' && value !== null && typeof value !== 'object'
}

function normalizeFieldTypes(runner: EventPipelineRunner, event: PluginEvent): Promise<void>[] {
    // People sometimes send things like strings in fields where we expect an object. Because we
    // don't do real schema validation and TypeScript is none the wiser at runtime, it's easy to
    // accidentally splat a string into an object, for example:
    //   event.properties.$set = { ...properties['$set'], ...event['$set'] }
    // If event.$set is simply "foo" then this will iterate over the string and add
    //   { 0: f, 1: o, 2: o }
    // To the event.$set object, which is definitely not what we or the customer want.

    const kafkaAcks: Promise<void>[] = []

    const writeWarning = (field: string, found_type: string) =>
        kafkaAcks.push(
            captureIngestionWarning(runner.hub.db.kafkaProducer, event.team_id, 'invalid_type_for_object_field', {
                field,
                type: found_type,
                eventUuid: event.uuid,
                event: event.event,
                distinctId: event.distinct_id,
            })
        )

    if (event.properties) {
        if (isNotNullOrUndefinedOrObject(event.properties)) {
            event.properties = {}
            writeWarning('properties', typeof event.properties)
        } else {
            if (isNotNullOrUndefinedOrObject(event.properties['$set'])) {
                event.properties['$set'] = {}
                writeWarning('properties.$set', typeof event.properties['$set'])
            }

            if (isNotNullOrUndefinedOrObject(event.properties['$set_once'])) {
                event.properties['$set_once'] = {}
                writeWarning('properties.$set_once', typeof event.properties['$set_once'])
            }
        }
    }

    if (isNotNullOrUndefinedOrObject(event.$set)) {
        event.$set = {}
        writeWarning('$set', typeof event.$set)
    }

    if (isNotNullOrUndefinedOrObject(event.$set_once)) {
        event.$set_once = {}
        writeWarning('$set_once', typeof event.$set_once)
    }

    return kafkaAcks
}

export function normalizeEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    processPerson: boolean
): Promise<[PluginEvent, DateTime, Promise<void>[]]> {
    let timestamp: DateTime
    try {
        const kafkaAcks = normalizeFieldTypes(runner, event)
        event = normalizeEvent(event)
        event = normalizeProcessPerson(event, processPerson)
        timestamp = parseEventTimestamp(event)

        // We need to be "async" to deal with how `runStep` currently works.
        return Promise.resolve([event, timestamp, kafkaAcks])
    } catch (error) {
        status.warn('⚠️', 'Failed normalizing event', {
            team_id: event.team_id,
            uuid: event.uuid,
            error,
        })
        throw error
    }
}

import { Message } from 'node-rdkafka'

import { sanitizeString } from '~/utils/db/utils'

import { IncomingEvent, PipelineEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

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
function sanitizeEvent<T extends PipelineEvent>(event: T): T {
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

function parseKafkaMessage(message: Message): IncomingEvent | null {
    try {
        // Parse the message payload into the event object
        const { data: dataStr, ...rawEvent } = parseJSON(message.value!.toString())
        const combinedEvent: PipelineEvent = { ...parseJSON(dataStr), ...rawEvent }
        // Use sanitize-only normalization here. Full normalization (including
        // personInitialAndUTMProperties) happens after transformations in normalizeEventStep.
        const event: PipelineEvent = sanitizeEvent(combinedEvent)

        return { event }
    } catch (error) {
        logger.warn('Failed to parse Kafka message', { error })
        return null
    }
}

export function createParseKafkaMessageStep<T extends { message: Message }>(): ProcessingStep<
    T,
    T & { event: IncomingEvent }
> {
    return async function parseKafkaMessageStep(input) {
        const { message } = input

        const parsedEvent = parseKafkaMessage(message)
        if (!parsedEvent) {
            return Promise.resolve(drop('failed_parse_message'))
        }

        return Promise.resolve(ok({ ...input, event: parsedEvent }))
    }
}

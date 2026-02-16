import { Message } from 'node-rdkafka'

import { sanitizeEvent } from '~/utils/event'

import { IncomingEvent, PipelineEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { dlq, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

type ParseResult = { event: IncomingEvent } | { error: Error }

function parseKafkaMessage(message: Message): ParseResult {
    try {
        // Parse the message payload into the event object
        const { data: dataStr, ...rawEvent } = parseJSON(message.value!.toString())
        const combinedEvent: PipelineEvent = { ...parseJSON(dataStr), ...rawEvent }
        // Use sanitize-only normalization here. Full normalization (including
        // personInitialAndUTMProperties) happens after transformations in normalizeEventStep.
        const event: PipelineEvent = sanitizeEvent(combinedEvent)

        return { event: { event } }
    } catch (error) {
        logger.warn('Failed to parse Kafka message', { error })
        return { error: error instanceof Error ? error : new Error(String(error)) }
    }
}

export function createParseKafkaMessageStep<T extends { message: Message }>(): ProcessingStep<
    T,
    T & { event: IncomingEvent }
> {
    return async function parseKafkaMessageStep(input) {
        const { message } = input

        const result = parseKafkaMessage(message)
        if ('error' in result) {
            return Promise.resolve(dlq('failed_parse_message', result.error))
        }

        return Promise.resolve(ok({ ...input, event: result.event }))
    }
}

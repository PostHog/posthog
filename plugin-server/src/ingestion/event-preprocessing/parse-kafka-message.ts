import { Message } from 'node-rdkafka'

import { IncomingEvent, PipelineEvent } from '../../types'
import { normalizeEvent } from '../../utils/event'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

function parseKafkaMessage(message: Message): IncomingEvent | null {
    try {
        // Parse the message payload into the event object
        const { data: dataStr, ...rawEvent } = parseJSON(message.value!.toString())
        const combinedEvent: PipelineEvent = { ...parseJSON(dataStr), ...rawEvent }
        const event: PipelineEvent = normalizeEvent(combinedEvent)

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

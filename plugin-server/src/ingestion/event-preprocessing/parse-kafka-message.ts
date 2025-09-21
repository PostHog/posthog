import { Message } from 'node-rdkafka'

import { IncomingEvent, PipelineEvent } from '../../types'
import { normalizeEvent } from '../../utils/event'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { drop, ok } from '../pipelines/results'
import { SyncProcessingStep } from '../pipelines/steps'

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

export function createParseKafkaMessageStep<T extends { message: Message }>(): SyncProcessingStep<
    T,
    T & { event: IncomingEvent }
> {
    return function parseKafkaMessageStep(input) {
        const { message } = input

        const parsedEvent = parseKafkaMessage(message)
        if (!parsedEvent) {
            return drop('Failed to parse Kafka message')
        }

        return ok({ ...input, event: parsedEvent })
    }
}

import { Message } from 'node-rdkafka'

import { IncomingEvent, PipelineEvent } from '../../types'
import { normalizeEvent } from '../../utils/event'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { drop, success } from '../../worker/ingestion/event-pipeline/pipeline-step-result'
import { SyncPreprocessingStep } from '../processing-pipeline'

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

export function createParseKafkaMessageStep<T extends { message: Message }>(): SyncPreprocessingStep<
    T,
    T & { event: IncomingEvent }
> {
    return (input) => {
        const { message } = input

        const parsedEvent = parseKafkaMessage(message)
        if (!parsedEvent) {
            return drop('Failed to parse Kafka message')
        }

        return success({ ...input, event: parsedEvent })
    }
}

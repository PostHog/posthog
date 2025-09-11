import { Message } from 'node-rdkafka'

import { IncomingEvent, PipelineEvent } from '../../types'
import { normalizeEvent } from '../../utils/event'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'

export function parseKafkaMessage(message: Message): IncomingEvent | null {
    try {
        // Parse the message payload into the event object
        const { data: dataStr, ...rawEvent } = parseJSON(message.value!.toString())
        const combinedEvent: PipelineEvent = { ...parseJSON(dataStr), ...rawEvent }
        const event: PipelineEvent = normalizeEvent(combinedEvent)

        return { message, event }
    } catch (error) {
        logger.warn('Failed to parse Kafka message', { error })
        return null
    }
}

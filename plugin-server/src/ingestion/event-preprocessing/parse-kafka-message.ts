import { Message } from 'node-rdkafka'

import { IncomingEvent, PipelineEvent } from '../../types'
import { normalizeEvent } from '../../utils/event'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'

export function parseKafkaMessage(message: Message): IncomingEvent | null {
    try {
        const { data, ...rawEvent } = parseJSON(message.value!.toString())

        if (data === undefined) {
            logger.warn('Failed to parse Kafka message', { error: new Error('Missing data field') })
            return null
        }

        const eventData = typeof data === 'string' ? parseJSON(data) : data
        const combinedEvent: PipelineEvent = { ...eventData, ...rawEvent }
        const event: PipelineEvent = normalizeEvent(combinedEvent)

        return { message, event }
    } catch (error) {
        logger.warn('Failed to parse Kafka message', { error })
        return null
    }
}

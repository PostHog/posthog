import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { captureIngestionWarning } from './utils'

/**
 * Helper function to copy and extend headers from a Kafka message
 * Converts various header value types to strings and adds new headers
 */
function copyAndExtendHeaders(
    originalMessage: Message,
    additionalHeaders: Record<string, string>
): Record<string, string> {
    const originalHeaders = originalMessage.headers || []
    const stringHeaders: Record<string, string> = {}

    // Kafka headers are always in array format (MessageHeader[])
    for (const headerObj of originalHeaders) {
        for (const [key, value] of Object.entries(headerObj)) {
            if (value === undefined) {
                // Skip undefined values
                continue
            } else if (typeof value === 'string') {
                stringHeaders[key] = value
            } else if (Buffer.isBuffer(value)) {
                stringHeaders[key] = value.toString()
            } else {
                // Convert all other values (including null) to strings
                stringHeaders[key] = String(value)
            }
        }
    }

    return {
        ...stringHeaders,
        ...additionalHeaders,
    }
}

/**
 * Extract event metadata from a Kafka message for logging purposes
 * Only extracts from headers as strings, never parses the payload
 */
function getEventMetadata(message: Message): { teamId?: string; distinctId?: string; event?: string; uuid?: string } {
    const originalHeaders = message.headers || []
    const headers: Record<string, any> = {}

    // Kafka headers are always in array format (MessageHeader[])
    for (const headerObj of originalHeaders) {
        for (const [key, value] of Object.entries(headerObj)) {
            headers[key] = value
        }
    }

    const teamId = headers['team_id'] ? String(headers['team_id']) : undefined
    const distinctId = headers['distinct_id'] ? String(headers['distinct_id']) : undefined
    const event = headers['event'] ? String(headers['event']) : undefined
    const uuid = headers['uuid'] ? String(headers['uuid']) : undefined

    return {
        teamId,
        distinctId,
        event,
        uuid,
    }
}

/**
 * Send a Kafka message to the dead letter queue with proper logging and metrics
 */
export async function sendMessageToDLQ(
    kafkaProducer: KafkaProducerWrapper,
    originalMessage: Message,
    error: unknown,
    stepName: string,
    dlqTopic: string
): Promise<void> {
    const step = stepName
    const messageInfo = getEventMetadata(originalMessage)

    logger.warn('Event sent to DLQ', {
        step,
        team_id: messageInfo.teamId,
        distinct_id: messageInfo.distinctId,
        event: messageInfo.event,
        uuid: messageInfo.uuid,
        error: error instanceof Error ? error.message : String(error),
    })

    try {
        if (messageInfo.teamId) {
            await captureIngestionWarning(
                kafkaProducer,
                parseInt(messageInfo.teamId, 10),
                'pipeline_step_dlq',
                {
                    distinctId: messageInfo.distinctId || 'unknown',
                    eventUuid: messageInfo.uuid || 'unknown',
                    error: error instanceof Error ? error.message : String(error),
                    event: messageInfo.event || 'unknown',
                    step,
                },
                { alwaysSend: true }
            )
        }

        await kafkaProducer.produce({
            topic: dlqTopic,
            value: originalMessage.value,
            key: originalMessage.key ?? null,
            headers: copyAndExtendHeaders(originalMessage, {
                dlq_reason: error instanceof Error ? error.message : String(error),
                dlq_step: step,
                dlq_timestamp: new Date().toISOString(),
                dlq_topic: originalMessage.topic,
                dlq_partition: String(originalMessage.partition),
                dlq_offset: String(originalMessage.offset),
            }),
        })
    } catch (dlqError) {
        logger.error('Failed to send event to DLQ', {
            step,
            team_id: messageInfo.teamId,
            distinct_id: messageInfo.distinctId,
            event: messageInfo.event,
            uuid: messageInfo.uuid,
            error: dlqError,
        })
        captureException(dlqError, {
            tags: { team_id: messageInfo.teamId, pipeline_step: step },
            extra: { originalMessage, error: dlqError },
        })
    }
}

/**
 * Redirect a Kafka message to a specified Kafka topic
 */
export async function redirectMessageToTopic(
    kafkaProducer: KafkaProducerWrapper,
    promiseScheduler: PromiseScheduler,
    originalMessage: Message,
    topic: string,
    stepName?: string,
    preserveKey: boolean = true,
    awaitAck: boolean = true
): Promise<void> {
    const step = stepName || 'unknown'

    try {
        const headers = copyAndExtendHeaders(originalMessage, {
            'redirect-step': step,
            'redirect-timestamp': new Date().toISOString(),
        })

        const producePromise = kafkaProducer.produce({
            topic: topic,
            value: originalMessage.value,
            key: preserveKey ? (originalMessage.key ?? null) : null,
            headers: headers,
        })

        const promise = promiseScheduler.schedule(producePromise)

        if (awaitAck) {
            await promise
        }
    } catch (redirectError) {
        const eventMetadata = getEventMetadata(originalMessage)
        captureException(redirectError, {
            tags: {
                team_id: eventMetadata.teamId,
                pipeline_step: step,
            },
            extra: {
                topic,
                distinct_id: eventMetadata.distinctId,
                event: eventMetadata.event,
                error: redirectError,
            },
        })
        throw redirectError
    }
}

/**
 * Log a dropped event from a Kafka message with proper metrics
 */
export function logDroppedMessage(originalMessage: Message, reason: string, stepName?: string): void {
    const step = stepName || 'unknown'
    const messageInfo = getEventMetadata(originalMessage)

    logger.debug('Event dropped', {
        step,
        team_id: messageInfo.teamId,
        distinct_id: messageInfo.distinctId,
        event: messageInfo.event,
        reason,
    })
}

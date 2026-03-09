import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { PipelineEvent } from '../../types'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { droppedEventCounter, pipelineStepDLQCounter, pipelineStepRedirectCounter } from './event-pipeline/metrics'
import { captureIngestionWarning, generateEventDeadLetterQueueMessage } from './utils'

/**
 * Send an event to the dead letter queue with proper logging and metrics
 */
export function sendEventToDLQ(
    kafkaProducer: KafkaProducerWrapper,
    originalEvent: PipelineEvent,
    error: unknown,
    stepName: string,
    teamId?: number
): void {
    const step = stepName
    const eventTeamId = teamId || originalEvent.team_id || 0

    logger.warn('Event sent to DLQ', {
        step,
        team_id: eventTeamId,
        distinct_id: originalEvent.distinct_id,
        event: originalEvent.event,
        error: error instanceof Error ? error.message : String(error),
    })

    pipelineStepDLQCounter.labels(step).inc()

    try {
        captureIngestionWarning(
            kafkaProducer,
            eventTeamId,
            'pipeline_step_dlq',
            {
                distinctId: originalEvent.distinct_id || 'unknown',
                eventUuid: originalEvent.uuid || 'unknown',
                error: error instanceof Error ? error.message : String(error),
                event: originalEvent.event || 'unknown',
                step,
            },
            { alwaysSend: true }
        )

        const dlqMessage = generateEventDeadLetterQueueMessage(
            originalEvent,
            error || new Error('Pipeline step returned DLQ result'),
            eventTeamId,
            `plugin_server_ingest_event:${step}`
        )

        kafkaProducer.enqueueMessages(dlqMessage)
    } catch (dlqError) {
        logger.error('Failed to send event to DLQ', {
            step,
            team_id: eventTeamId,
            distinct_id: originalEvent.distinct_id,
            error: dlqError,
        })
        captureException(dlqError, {
            tags: { team_id: eventTeamId, pipeline_step: step },
            extra: { originalEvent, error: dlqError },
        })
    }
}

/**
 * Redirect an event to a specified Kafka topic
 */
export function redirectEventToTopic(
    kafkaProducer: KafkaProducerWrapper,
    originalEvent: PipelineEvent,
    topic: string,
    stepName?: string,
    preserveKey: boolean = true
): void {
    const step = stepName || 'unknown'
    const teamId = originalEvent.team_id || 0

    logger.info('Event redirected to topic', {
        step,
        team_id: teamId,
        distinct_id: originalEvent.distinct_id,
        event: originalEvent.event,
        topic,
    })

    kafkaProducer.enqueue({
        topic: topic,
        key: preserveKey ? `${teamId}:${originalEvent.distinct_id}` : null,
        value: Buffer.from(JSON.stringify(originalEvent)),
        headers: {
            distinct_id: originalEvent.distinct_id || 'unknown',
            team_id: teamId.toString(),
        },
    })

    logger.info('Event successfully redirected to topic', {
        team_id: teamId,
        distinct_id: originalEvent.distinct_id,
        event: originalEvent.event,
        topic,
    })
}

// ============================================================================
// Message-based helper functions for PipelineResultHandler
// ============================================================================

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
export function sendMessageToDLQ(
    kafkaProducer: KafkaProducerWrapper,
    originalMessage: Message,
    error: unknown,
    stepName: string,
    dlqTopic: string
): void {
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

    pipelineStepDLQCounter.labels(step).inc()

    try {
        if (messageInfo.teamId) {
            captureIngestionWarning(
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

        kafkaProducer.enqueue({
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
export function redirectMessageToTopic(
    kafkaProducer: KafkaProducerWrapper,
    _promiseScheduler: PromiseScheduler,
    originalMessage: Message,
    topic: string,
    stepName?: string,
    preserveKey: boolean = true
): void {
    const step = stepName || 'unknown'

    pipelineStepRedirectCounter.inc({
        step_name: step,
        target_topic: topic,
        preserve_key: preserveKey.toString(),
    })

    const headers = copyAndExtendHeaders(originalMessage, {
        'redirect-step': step,
        'redirect-timestamp': new Date().toISOString(),
    })

    kafkaProducer.enqueue({
        topic: topic,
        value: originalMessage.value,
        key: preserveKey ? (originalMessage.key ?? null) : null,
        headers: headers,
    })
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

    droppedEventCounter.labels({ reason }).inc()
}

import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { PipelineEvent } from '../../types'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { droppedEventCounter, pipelineStepDLQCounter } from './event-pipeline/metrics'
import { captureIngestionWarning, generateEventDeadLetterQueueMessage } from './utils'

/**
 * Send an event to the dead letter queue with proper logging and metrics
 */
export async function sendEventToDLQ(
    kafkaProducer: KafkaProducerWrapper,
    originalEvent: PipelineEvent,
    error: unknown,
    stepName: string,
    teamId?: number
): Promise<void> {
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
        await captureIngestionWarning(
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

        await kafkaProducer.queueMessages(dlqMessage)
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
export async function redirectEventToTopic(
    kafkaProducer: KafkaProducerWrapper,
    originalEvent: PipelineEvent,
    topic: string,
    stepName?: string
): Promise<void> {
    const step = stepName || 'unknown'
    const teamId = originalEvent.team_id || 0

    logger.info('Event redirected to topic', {
        step,
        team_id: teamId,
        distinct_id: originalEvent.distinct_id,
        event: originalEvent.event,
        topic,
    })

    try {
        await kafkaProducer.produce({
            topic: topic,
            key: `${teamId}:${originalEvent.distinct_id}`,
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
    } catch (redirectError) {
        logger.error('Failed to redirect event to topic', {
            team_id: teamId,
            distinct_id: originalEvent.distinct_id,
            topic,
            error: redirectError,
        })
        captureException(redirectError, {
            tags: { team_id: teamId, pipeline_step: step },
            extra: { originalEvent, topic, error: redirectError },
        })
        throw redirectError // Re-throw to ensure the pipeline handles the failure appropriately
    }
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
    const originalHeaders = originalMessage.headers || {}
    const stringHeaders: Record<string, string> = {}

    for (const [key, value] of Object.entries(originalHeaders)) {
        if (typeof value === 'string') {
            stringHeaders[key] = value
        } else if (Buffer.isBuffer(value)) {
            stringHeaders[key] = value.toString()
        } else if (value !== undefined && value !== null) {
            stringHeaders[key] = String(value)
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
function getEventMetadata(message: Message): { teamId?: string; distinctId?: string; event?: string } {
    const headers = (message.headers || {}) as any

    const teamId = headers['team-id'] ? String(headers['team-id']) : undefined
    const distinctId = headers['distinct-id'] ? String(headers['distinct-id']) : undefined
    const event = headers['event'] ? String(headers['event']) : undefined

    return {
        teamId,
        distinctId,
        event,
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
        error: error instanceof Error ? error.message : String(error),
    })

    pipelineStepDLQCounter.labels(step).inc()

    try {
        if (messageInfo.teamId) {
            await captureIngestionWarning(
                kafkaProducer,
                parseInt(messageInfo.teamId, 10),
                'pipeline_step_dlq',
                {
                    distinctId: messageInfo.distinctId || 'unknown',
                    eventUuid: 'unknown', // We don't parse the full event
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
                'dlq-reason': error instanceof Error ? error.message : String(error),
                'dlq-step': step,
                'dlq-timestamp': new Date().toISOString(),
            }),
        })
    } catch (dlqError) {
        logger.error('Failed to send event to DLQ', {
            step,
            team_id: messageInfo.teamId,
            distinct_id: messageInfo.distinctId,
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
    originalMessage: Message,
    topic: string,
    stepName?: string
): Promise<void> {
    const step = stepName || 'unknown'
    const messageInfo = getEventMetadata(originalMessage)

    logger.info('Event redirected to topic', {
        step,
        team_id: messageInfo.teamId,
        distinct_id: messageInfo.distinctId,
        event: messageInfo.event,
        topic,
    })

    try {
        await kafkaProducer.produce({
            topic: topic,
            value: originalMessage.value,
            key: originalMessage.key ?? null,
            headers: copyAndExtendHeaders(originalMessage, {
                'redirect-step': step,
                'redirect-timestamp': new Date().toISOString(),
            }),
        })

        logger.info('Event successfully redirected to topic', {
            team_id: messageInfo.teamId,
            distinct_id: messageInfo.distinctId,
            event: messageInfo.event,
            topic,
        })
    } catch (redirectError) {
        logger.error('Failed to redirect event to topic', {
            team_id: messageInfo.teamId,
            distinct_id: messageInfo.distinctId,
            topic,
            error: redirectError,
        })
        captureException(redirectError, {
            tags: { team_id: messageInfo.teamId, pipeline_step: step },
            extra: { originalMessage, topic, error: redirectError },
        })
        throw redirectError // Re-throw to ensure the pipeline handles the failure appropriately
    }
}

/**
 * Log a dropped event from a Kafka message with proper metrics
 */
export function logDroppedMessage(originalMessage: Message, reason: string, stepName?: string): void {
    const step = stepName || 'unknown'
    const messageInfo = getEventMetadata(originalMessage)

    logger.info('Event dropped', {
        step,
        team_id: messageInfo.teamId,
        distinct_id: messageInfo.distinctId,
        event: messageInfo.event,
        reason,
    })

    droppedEventCounter.inc()
}

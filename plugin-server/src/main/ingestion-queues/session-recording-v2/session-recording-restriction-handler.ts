import { Message } from 'node-rdkafka'

import { parseEventHeaders, parseKafkaHeaders } from '../../../kafka/consumer'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { EventIngestionRestrictionManager } from '../../../utils/event-ingestion-restriction-manager'
import { logger } from '../../../utils/logger'
import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { SessionRecordingIngesterMetrics } from './metrics'

export class SessionRecordingRestrictionHandler {
    constructor(
        private restrictionManager: EventIngestionRestrictionManager,
        private overflowTopic: string,
        private overflowProducer: KafkaProducerWrapper | undefined,
        private promiseScheduler: PromiseScheduler,
        private consumeOverflow: boolean
    ) {}

    /**
     * Apply event ingestion restrictions to session recording messages.
     * Filters out dropped messages and redirects overflow messages.
     * Returns only messages that should be processed normally.
     */
    applyRestrictions(messages: Message[]): Message[] {
        const filteredMessages: Message[] = []
        const overflowMessages: Message[] = []
        let droppedCount = 0

        for (const message of messages) {
            const headers = parseEventHeaders(message.headers)
            const { token, distinct_id } = headers

            if (!token) {
                // If there's no token, we can't check restrictions, so keep the message
                filteredMessages.push(message)
                continue
            }

            // Check if this message should be dropped
            if (this.restrictionManager.shouldDropEvent(token, distinct_id)) {
                logger.info('🚫', 'session_recording_dropped_by_restriction', {
                    token,
                    distinct_id,
                    partition: message.partition,
                    offset: message.offset,
                })
                droppedCount++
                continue
            }

            // Check if this message should be forced to overflow
            if (!this.consumeOverflow && this.restrictionManager.shouldForceOverflow(token, distinct_id)) {
                overflowMessages.push(message)
                continue
            }

            filteredMessages.push(message)
        }

        // Redirect overflow messages if any
        if (overflowMessages.length > 0) {
            if (!this.overflowProducer) {
                throw new Error(
                    `Cannot redirect ${overflowMessages.length} messages to overflow: no overflow producer available`
                )
            }
            SessionRecordingIngesterMetrics.observeOverflowedByRestrictions(overflowMessages.length)
            void this.promiseScheduler.schedule(this.emitToOverflow(overflowMessages))
        }

        if (droppedCount > 0) {
            SessionRecordingIngesterMetrics.observeDroppedByRestrictions(droppedCount)
        }

        return filteredMessages
    }

    private async emitToOverflow(kafkaMessages: Message[]): Promise<void> {
        if (!this.overflowProducer) {
            logger.warn('🪣', 'No overflow producer available, cannot redirect messages')
            return
        }

        await Promise.all(
            kafkaMessages.map((message) => {
                logger.info('🪣', 'session_recording_redirected_to_overflow', {
                    partition: message.partition,
                    offset: message.offset,
                })
                return this.overflowProducer!.produce({
                    topic: this.overflowTopic,
                    value: message.value,
                    key: message.key ?? null,
                    headers: parseKafkaHeaders(message.headers),
                })
            })
        )
    }
}

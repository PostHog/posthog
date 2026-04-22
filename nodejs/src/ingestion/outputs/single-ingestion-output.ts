import { KafkaProducerWrapper, MessageKey } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { IngestionOutput } from './ingestion-output'
import {
    ingestionOutputsBatchSize,
    ingestionOutputsErrors,
    ingestionOutputsLatency,
    ingestionOutputsMessageValueBytes,
} from './metrics'
import { IngestionOutputMessage } from './types'

/** Single-target output. */
export class SingleIngestionOutput implements IngestionOutput {
    private readonly labels: { output: string; producer_name: string; topic: string }

    constructor(
        readonly outputName: string,
        readonly topic: string,
        readonly producer: KafkaProducerWrapper,
        readonly producerName: string
    ) {
        this.labels = { output: outputName, producer_name: producerName, topic }
    }

    async produce(message: IngestionOutputMessage & { key: MessageKey }): Promise<void> {
        ingestionOutputsMessageValueBytes.observe(this.labels, message.value?.length ?? 0)
        ingestionOutputsBatchSize.observe({ ...this.labels, method: 'produce' }, 1)
        await withMetrics(this.labels, 'produce', () => this.producer.produce({ ...message, topic: this.topic }))
    }

    async queueMessages(messages: IngestionOutputMessage[]): Promise<void> {
        for (const m of messages) {
            ingestionOutputsMessageValueBytes.observe(this.labels, m.value?.length ?? 0)
        }
        ingestionOutputsBatchSize.observe({ ...this.labels, method: 'queueMessages' }, messages.length)
        await withMetrics(this.labels, 'queueMessages', () =>
            this.producer.queueMessages({ topic: this.topic, messages })
        )
    }

    async checkHealth(timeoutMs: number): Promise<void> {
        try {
            await this.producer.checkConnection(timeoutMs)
        } catch (error) {
            logger.error('🔴', `Producer health check failed for "${this.producerName}" topic "${this.topic}"`, {
                error,
            })
            throw error
        }
    }

    async checkTopicExists(timeoutMs: number): Promise<void> {
        if (!this.topic) {
            return
        }
        try {
            await this.producer.checkTopicExists(this.topic, timeoutMs)
        } catch (error) {
            logger.error('🔴', `Topic check failed for "${this.producerName}" topic "${this.topic}"`, { error })
            throw error
        }
    }
}

async function withMetrics<T>(
    labels: { output: string; producer_name: string; topic: string },
    method: string,
    fn: () => Promise<T>
): Promise<T> {
    const metricLabels = { ...labels, method }
    const end = ingestionOutputsLatency.startTimer(metricLabels)
    try {
        return await fn()
    } catch (error) {
        ingestionOutputsErrors.inc(metricLabels)
        throw error
    } finally {
        end()
    }
}

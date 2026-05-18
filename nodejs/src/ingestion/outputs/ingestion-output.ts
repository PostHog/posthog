import { MessageKey } from '../../kafka/producer'
import { IngestionOutputMessage } from './types'

/** A resolved Kafka output that pipeline steps produce to. */
export interface IngestionOutput {
    produce(message: IngestionOutputMessage & { key: MessageKey }): Promise<void>
    queueMessages(messages: IngestionOutputMessage[]): Promise<void>
    checkHealth(timeoutMs: number): Promise<void>
    checkTopicExists(timeoutMs: number): Promise<void>
    /**
     * Idempotently create the underlying topic on the broker. Should only be
     * called during dev/local startup — see `KafkaProducerWrapper.ensureTopicExists`.
     */
    ensureTopicExists(): Promise<void>
}

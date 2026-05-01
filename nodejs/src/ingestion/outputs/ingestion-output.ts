import { MessageKey } from '../../kafka/producer'
import { IngestionOutputMessage } from './types'

/** A resolved Kafka output that pipeline steps produce to. */
export interface IngestionOutput {
    produce(message: IngestionOutputMessage & { key: MessageKey }): Promise<void>
    queueMessages(messages: IngestionOutputMessage[]): Promise<void>
    checkHealth(timeoutMs: number): Promise<void>
    checkTopicExists(timeoutMs: number): Promise<void>
}

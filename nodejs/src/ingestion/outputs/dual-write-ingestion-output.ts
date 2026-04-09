import { MessageKey } from '../../kafka/producer'
import { IngestionOutput } from './ingestion-output'
import { SingleIngestionOutput } from './single-ingestion-output'
import { IngestionOutputMessage } from './types'

/** Dual-write output — fans out to primary and secondary in parallel. */
export class DualWriteIngestionOutput implements IngestionOutput {
    constructor(
        private readonly primary: SingleIngestionOutput,
        private readonly secondary: SingleIngestionOutput
    ) {}

    async produce(message: IngestionOutputMessage & { key: MessageKey }): Promise<void> {
        await Promise.all([this.primary.produce(message), this.secondary.produce(message)])
    }

    async queueMessages(messages: IngestionOutputMessage[]): Promise<void> {
        await Promise.all([this.primary.queueMessages(messages), this.secondary.queueMessages(messages)])
    }

    async checkHealth(timeoutMs: number): Promise<void> {
        await Promise.all([this.primary.checkHealth(timeoutMs), this.secondary.checkHealth(timeoutMs)])
    }

    async checkTopicExists(timeoutMs: number): Promise<void> {
        await Promise.all([this.primary.checkTopicExists(timeoutMs), this.secondary.checkTopicExists(timeoutMs)])
    }
}

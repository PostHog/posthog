import { MessageKey } from '~/common/kafka/producer'

import { IngestionOutput } from './ingestion-output'
import { ingestionOutputsDroppedMessages } from './metrics'
import { IngestionOutputMessage } from './types'

/** Discards every message; health and topic checks always pass. */
export class DroppedIngestionOutput implements IngestionOutput {
    constructor(readonly outputName: string) {}

    produce(_message: IngestionOutputMessage & { key: MessageKey }): Promise<void> {
        ingestionOutputsDroppedMessages.inc({ output: this.outputName })
        return Promise.resolve()
    }

    queueMessages(messages: IngestionOutputMessage[]): Promise<void> {
        ingestionOutputsDroppedMessages.inc({ output: this.outputName }, messages.length)
        return Promise.resolve()
    }

    checkHealth(_timeoutMs: number): Promise<void> {
        return Promise.resolve()
    }

    checkTopicExists(_timeoutMs: number): Promise<void> {
        return Promise.resolve()
    }
}

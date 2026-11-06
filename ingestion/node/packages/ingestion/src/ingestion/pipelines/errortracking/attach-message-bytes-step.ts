import { Message } from 'node-rdkafka'

import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

/**
 * Carries the Kafka message byte size on the value, so downstream chunk steps
 * (Cymbal batch chunking) can budget by payload size.
 */
export function createAttachMessageBytesStep<T extends { message: Message }>(): ProcessingStep<
    T,
    T & { messageBytes: number }
> {
    return function attachMessageBytesStep(input) {
        return Promise.resolve(ok({ ...input, messageBytes: input.message.value?.length ?? 0 }))
    }
}

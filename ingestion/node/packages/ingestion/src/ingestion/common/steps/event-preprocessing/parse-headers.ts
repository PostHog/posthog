import { Message } from 'node-rdkafka'

import { parseEventHeaders } from '@posthog/node-common/kafka/consumer/index'

import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders } from '~/types'

export function createParseHeadersStep<T extends { message: Pick<Message, 'headers'> }>(): ProcessingStep<
    T,
    T & { headers: EventHeaders }
> {
    return async function parseHeadersStep(input) {
        const { message } = input
        const parsedHeaders = parseEventHeaders(message.headers)
        return Promise.resolve(ok({ ...input, headers: parsedHeaders }))
    }
}

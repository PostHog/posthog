import { Message } from 'node-rdkafka'

import { parseEventHeaders } from '../../kafka/consumer'
import { EventHeaders } from '../../types'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

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

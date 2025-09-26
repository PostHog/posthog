import { Message } from 'node-rdkafka'

import { parseEventHeaders } from '../../kafka/consumer'
import { EventHeaders } from '../../types'
import { ok } from '../pipelines/results'
import { SyncProcessingStep } from '../pipelines/steps'

export function createParseHeadersStep<T extends { message: Pick<Message, 'headers'> }>(): SyncProcessingStep<
    T,
    T & { headers: EventHeaders }
> {
    return function parseHeadersStep(input) {
        const { message } = input
        const parsedHeaders = parseEventHeaders(message.headers)
        return ok({ ...input, headers: parsedHeaders })
    }
}

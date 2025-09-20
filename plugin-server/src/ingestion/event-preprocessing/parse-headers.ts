import { Message } from 'node-rdkafka'

import { parseEventHeaders } from '../../kafka/consumer'
import { EventHeaders } from '../../types'
import { SyncProcessingStep, success } from '../pipelines/pipeline-types'

export function createParseHeadersStep<T extends { message: Pick<Message, 'headers'> }>(): SyncProcessingStep<
    T,
    T & { headers: EventHeaders }
> {
    return function parseHeadersStep(input) {
        const { message } = input
        const parsedHeaders = parseEventHeaders(message.headers)
        return success({ ...input, headers: parsedHeaders })
    }
}

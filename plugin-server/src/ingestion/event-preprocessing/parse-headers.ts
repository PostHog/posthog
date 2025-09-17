import { Message } from 'node-rdkafka'

import { parseEventHeaders } from '../../kafka/consumer'
import { EventHeaders } from '../../types'
import { success } from '../../worker/ingestion/event-pipeline/pipeline-step-result'
import { SyncPreprocessingStep } from '../processing-pipeline'

export function createParseHeadersStep<T extends { message: Pick<Message, 'headers'> }>(): SyncPreprocessingStep<
    T,
    T & { headers: EventHeaders }
> {
    return (input) => {
        const { message } = input
        const parsedHeaders = parseEventHeaders(message.headers)
        return success({ ...input, headers: parsedHeaders })
    }
}

import { Message } from 'node-rdkafka'

import { parseEventHeaders } from '../../kafka/consumer'
import { EventHeaders } from '../../types'
import { success } from '../../worker/ingestion/event-pipeline/pipeline-step-result'
import { SyncPreprocessingStep } from '../preprocessing-pipeline'

export function createParseHeadersStep(): SyncPreprocessingStep<Message, { message: Message; headers: EventHeaders }> {
    return (message: Message) => {
        const headers = parseEventHeaders(message.headers)
        return success({ message, headers })
    }
}

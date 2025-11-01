import { Message } from 'node-rdkafka'

import { PipelineResult, ok } from '../../../../ingestion/pipelines/results'
import { ProcessingStep } from '../../../../ingestion/pipelines/steps'
import { parseEventHeaders } from '../../../../kafka/consumer'
import { EventHeaders } from '../../../../types'

type Input = { message: Pick<Message, 'headers'> }
type Output = { headers: EventHeaders }

export function createParseHeadersStep<T extends Input>(): ProcessingStep<T, T & Output> {
    return function parseHeadersStep(input: T): Promise<PipelineResult<T & Output>> {
        const headers = parseEventHeaders(input.message.headers)

        return Promise.resolve(ok({ ...input, headers }))
    }
}

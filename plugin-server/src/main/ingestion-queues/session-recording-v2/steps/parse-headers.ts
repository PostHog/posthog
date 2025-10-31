import { Message } from 'node-rdkafka'

import { PipelineResult, ok } from '../../../../ingestion/pipelines/results'
import { ProcessingStep } from '../../../../ingestion/pipelines/steps'
import { parseEventHeaders } from '../../../../kafka/consumer'
import { EventHeaders } from '../../../../types'

type Input = { message: Message }
type Output = { message: Message; headers: EventHeaders }

export function createParseHeadersStep(): ProcessingStep<Input, Output> {
    return function parseHeadersStep(input: Input): Promise<PipelineResult<Output>> {
        const headers = parseEventHeaders(input.message.headers)

        return Promise.resolve(
            ok({
                message: input.message,
                headers,
            })
        )
    }
}

import { Message } from 'node-rdkafka'

import { KafkaMessageParser } from '../../session-recording/kafka/message-parser'
import { ParsedMessageData } from '../../session-recording/kafka/types'
import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { drop, ok } from '../pipelines/results'

export interface ParseMessageStepInput {
    message: Message
}

/**
 * Step that parses raw Kafka messages into ParsedMessageData.
 * Accepts input with a `message` property (e.g., restriction pipeline output).
 * Drops messages that fail to parse.
 */
export function createParseMessageStep(
    parser: KafkaMessageParser
): BatchProcessingStep<ParseMessageStepInput, ParsedMessageData> {
    return async function parseMessageStep(inputs) {
        return Promise.all(
            inputs.map(async (input) => {
                const result = await parser.parseMessage(input.message)
                return result ? ok(result) : drop('invalid_message')
            })
        )
    }
}

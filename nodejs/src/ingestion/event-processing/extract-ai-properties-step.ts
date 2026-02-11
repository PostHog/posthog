import { KafkaProducerWrapper } from '../../kafka/producer'
import { PreIngestionEvent, TimestampFormat } from '../../types'
import { castTimestampOrNow } from '../../utils/utils'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

const AI_EVENT_TYPES = new Set([
    '$ai_generation',
    '$ai_span',
    '$ai_trace',
    '$ai_embedding',
    '$ai_metric',
    '$ai_feedback',
])

const AI_LARGE_PROPERTIES = [
    '$ai_input',
    '$ai_output',
    '$ai_output_choices',
    '$ai_input_state',
    '$ai_output_state',
    '$ai_tools',
] as const

export interface ExtractAiPropertiesStepConfig {
    kafkaProducer: KafkaProducerWrapper
    CLICKHOUSE_AI_EVENT_PROPERTIES_KAFKA_TOPIC: string
}

export interface ExtractAiPropertiesStepInput {
    preparedEvent: PreIngestionEvent
}

export type ExtractAiPropertiesStepResult<TInput> = TInput & {
    preparedEvent: PreIngestionEvent
}

export function createExtractAiPropertiesStep<TInput extends ExtractAiPropertiesStepInput>(
    config: ExtractAiPropertiesStepConfig
): ProcessingStep<TInput, ExtractAiPropertiesStepResult<TInput>> {
    return function extractAiPropertiesStep(
        input: TInput
    ): Promise<PipelineResult<ExtractAiPropertiesStepResult<TInput>>> {
        const { preparedEvent } = input

        if (!AI_EVENT_TYPES.has(preparedEvent.event)) {
            return Promise.resolve(ok({ ...input }))
        }

        const { properties } = preparedEvent
        const acks: Promise<void>[] = []

        const record: Record<string, string> = {
            uuid: preparedEvent.eventUuid,
            team_id: String(preparedEvent.teamId),
            timestamp: castTimestampOrNow(preparedEvent.timestamp ?? null, TimestampFormat.ClickHouse),
        }

        let hasAnyProperty = false
        const strippedProperties = { ...properties }

        for (const prop of AI_LARGE_PROPERTIES) {
            if (prop in properties && properties[prop] != null) {
                record[prop.slice(1)] = JSON.stringify(properties[prop])
                hasAnyProperty = true
            }
            delete strippedProperties[prop]
        }

        if (hasAnyProperty) {
            acks.push(
                config.kafkaProducer.queueMessages({
                    topic: config.CLICKHOUSE_AI_EVENT_PROPERTIES_KAFKA_TOPIC,
                    messages: [
                        {
                            key: preparedEvent.eventUuid,
                            value: JSON.stringify(record),
                        },
                    ],
                })
            )
        }

        return Promise.resolve(
            ok(
                {
                    ...input,
                    preparedEvent: {
                        ...preparedEvent,
                        properties: strippedProperties,
                    },
                },
                acks
            )
        )
    }
}

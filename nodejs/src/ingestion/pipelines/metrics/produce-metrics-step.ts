import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { dlq, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { recordMetricsIngested } from './ingestion-otel-metrics'
import { metricMessageDlqCounter, metricMessageDroppedCounter } from './metrics'
import { DEFAULT_METRICS_RETENTION_DAYS, METRICS_OUTPUT, MetricsOutput } from './outputs/outputs'

export interface ProduceMetricsInput {
    message: Message
    token: string
    teamId: number
    bytesUncompressed: number
    recordCount: number
}

/**
 * Produces the capture-side Avro packet to the ClickHouse-bound topic as is.
 * The value is never decoded; the step only adds the headers ClickHouse reads
 * (`team_id`, `retention-days`) on top of the ones capture stamped.
 */
export function createProduceMetricsStep<T extends ProduceMetricsInput>(
    outputs: IngestionOutputs<MetricsOutput>
): ProcessingStep<T, void> {
    return async function produceMetricsStep(input) {
        const value = input.message.value
        const teamIdLabel = input.teamId.toString()
        if (value === null) {
            metricMessageDroppedCounter.inc({ reason: 'null_value', team_id: teamIdLabel })
            return drop('null_value')
        }

        try {
            await outputs.produce(METRICS_OUTPUT, {
                value,
                key: null,
                headers: {
                    ...parseKafkaHeaders(input.message.headers),
                    token: input.token,
                    team_id: teamIdLabel,
                    'retention-days': DEFAULT_METRICS_RETENTION_DAYS.toString(),
                },
            })
        } catch (error) {
            const errorName = error instanceof Error ? error.name : 'UnknownError'
            metricMessageDlqCounter.inc({ reason: errorName, team_id: teamIdLabel })
            return dlq('metrics_produce_failed', error)
        }

        // Only after the ClickHouse-bound produce resolves — messages that
        // fail and route to the DLQ must not count as ingested.
        recordMetricsIngested(input.teamId, input.bytesUncompressed, input.recordCount)
        return ok(undefined)
    }
}

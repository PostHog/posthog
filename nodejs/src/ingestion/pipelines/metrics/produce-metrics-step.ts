import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { DlqOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { retryIfRetriable } from '~/common/utils/retries'
import { produceMessageToDLQ } from '~/ingestion/framework/result-handling-helpers'
import { drop, ok } from '~/ingestion/framework/results'
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

const PRODUCE_RETRY = { tries: 3, sleepMs: 100 }

/**
 * Produces the capture-side Avro packet to the ClickHouse-bound topic as is.
 * The value is never decoded; the step only adds the headers ClickHouse reads
 * (`team_id`, `retention-days`) on top of the ones capture stamped.
 *
 * The produce is a side effect, so the consumer reads the next batch while
 * the acks are pending. A retriable error that outlasts the retries rejects
 * the side effect, which stops offset commits so the batch replays. Any other
 * error sends the message to the DLQ.
 */
export function createProduceMetricsStep<T extends ProduceMetricsInput>(
    outputs: IngestionOutputs<MetricsOutput | DlqOutput>
): ProcessingStep<T, void> {
    return function produceMetricsStep(input) {
        const value = input.message.value
        const teamIdLabel = input.teamId.toString()
        if (value === null) {
            metricMessageDroppedCounter.inc({ reason: 'null_value', team_id: teamIdLabel })
            return Promise.resolve(drop('null_value'))
        }

        const headers = { token: input.token, team_id: teamIdLabel }
        const produced = retryIfRetriable(
            () =>
                outputs.produce(METRICS_OUTPUT, {
                    value,
                    key: null,
                    headers: {
                        ...parseKafkaHeaders(input.message.headers),
                        ...headers,
                        'retention-days': DEFAULT_METRICS_RETENTION_DAYS.toString(),
                    },
                }),
            PRODUCE_RETRY
        ).then(
            // Only after the ClickHouse-bound produce resolves — messages that
            // fail and route to the DLQ must not count as ingested.
            () => recordMetricsIngested(input.teamId, input.bytesUncompressed, input.recordCount),
            async (error) => {
                if (error?.isRetriable === true) {
                    throw error
                }
                const errorName = error instanceof Error ? error.name : 'UnknownError'
                metricMessageDlqCounter.inc({ reason: errorName, team_id: teamIdLabel })
                const dlqMessage = {
                    ...input.message,
                    headers: [
                        ...(input.message.headers ?? []),
                        ...Object.entries(headers).map(([k, v]) => ({ [k]: v })),
                    ],
                }
                await produceMessageToDLQ(outputs, dlqMessage, error, 'produceMetricsStep')
            }
        )

        return Promise.resolve(ok(undefined, [produced]))
    }
}

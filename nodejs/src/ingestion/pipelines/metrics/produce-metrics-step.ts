import { Message } from 'node-rdkafka'

import { DlqOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { produceMessageToDLQ } from '~/ingestion/framework/result-handling-helpers'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { recordMetricsIngested } from './ingestion-otel-metrics'
import { metricMessageDlqCounter, metricMessageDroppedCounter } from './metrics'
import { retryAfterFirstFailure } from './metrics-retry'
import { DEFAULT_METRICS_RETENTION_DAYS, METRICS_OUTPUT, MetricsOutput } from './outputs/outputs'

export interface ProduceMetricsInput {
    message: Message
    kafkaHeaders: Record<string, string>
    token: string
    teamId: number
    bytesUncompressed: number
    recordCount: number
}

// A delivery timeout already includes librdkafka's own retries, so the deadline
// keeps a slow failure from waiting through more attempts.
const PRODUCE_RETRY = { tries: 5, sleepMs: 100, softDeadlineMs: 10_000, name: 'produce_metrics' }

/**
 * Produces the capture-side Avro packet to the ClickHouse-bound topic as is.
 * The value is never decoded; the step only adds the headers ClickHouse reads
 * (`team_id`, `retention-days`) on top of the ones capture stamped.
 *
 * The produce is a side effect, so the consumer reads the next batch while
 * the acks are pending. An error not marked `isRetriable: false` gets retries.
 * When the produce still fails, the message goes to the DLQ. The side effect must not reject:
 * consumer-v1 stores the batch's offsets even when its background task
 * rejects, so a rejection would lose the message instead of replaying it.
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
        const produced = retryAfterFirstFailure(
            () =>
                outputs.produce(METRICS_OUTPUT, {
                    value,
                    key: null,
                    headers: {
                        ...input.kafkaHeaders,
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

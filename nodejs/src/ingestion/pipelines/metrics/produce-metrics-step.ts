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

// A delivery timeout already includes librdkafka's retries. The deadline stops more attempts after a slow failure.
const PRODUCE_RETRY = { tries: 5, sleepMs: 100, softDeadlineMs: 10_000, name: 'produce_metrics' }

/**
 * A message that still fails after the retries goes to the DLQ. If the DLQ
 * write also fails, the side effect rejects and `MetricsPipelineConsumer`
 * replays the batch.
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
                await produceMessageToDLQ(outputs, dlqMessage, error, 'produceMetricsStep', {
                    rethrowOnFailure: true,
                })
            }
        )

        return Promise.resolve(ok(undefined, [produced]))
    }
}

import { AppMetricsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { logger } from '~/common/utils/logger'
import { UUID7 } from '~/common/utils/utils'
import { BeforeBatchStep } from '~/ingestion/framework/batching-pipeline'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import {
    metricsBytesAllowedCounter,
    metricsBytesDroppedCounter,
    metricsBytesReceivedCounter,
    metricsRecordsAllowedCounter,
    metricsRecordsDroppedCounter,
    metricsRecordsReceivedCounter,
} from './metrics'
import { MetricsUsageAccumulator, MetricsUsageBatchContext, UsageStats } from './metrics-usage'

export function createMetricsUsageBeforeBatchStep<TInput, CInput, CBatch>(): BeforeBatchStep<
    TInput,
    CInput,
    CBatch,
    CBatch & MetricsUsageBatchContext
> {
    return function metricsUsageBeforeBatchStep(input) {
        return Promise.resolve(
            ok({
                elements: input.elements,
                batchContext: { ...input.batchContext, usage: new MetricsUsageAccumulator() },
            })
        )
    }
}

export interface RecordMetricsReceivedInput {
    teamId: number
    bytesUncompressed: number
    recordCount: number
    usage: MetricsUsageAccumulator
}

export function createRecordMetricsReceivedStep<T extends RecordMetricsReceivedInput>(): ProcessingStep<T, T> {
    return function recordMetricsReceivedStep(input) {
        input.usage.recordReceived(input.teamId, input.bytesUncompressed, input.recordCount)
        return Promise.resolve(ok(input))
    }
}

const USAGE_METRIC_NAMES: [keyof UsageStats, string][] = [
    ['bytesReceived', 'bytes_received'],
    ['recordsReceived', 'records_received'],
    ['bytesAllowed', 'bytes_ingested'],
    ['bytesAllowedRecords', 'bytes_ingested_records'],
    ['recordsAllowed', 'records_ingested'],
    ['bytesDropped', 'bytes_dropped'],
    ['recordsDropped', 'records_dropped'],
]

const USAGE_RECORD_KEYS: [keyof UsageStats, string, string][] = [
    ['bytesAllowed', 'metrics_bytes', 'bytes'],
    ['bytesAllowedRecords', 'metrics_bytes_records', 'bytes'],
    ['recordsAllowed', 'metrics_records', 'records'],
]

export function addMetricsUsageRecords(
    usageBatch: UsageRecordBatch,
    usageByTeam: Iterable<[number, UsageStats]>
): void {
    for (const [teamId, stats] of usageByTeam) {
        // A fresh ID per flush stops two pods' flushes for one team from collapsing into one record.
        const flushId = new UUID7().toString()
        for (const [statKey, usageKey, unit] of USAGE_RECORD_KEYS) {
            usageBatch.add(teamId, usageKey, flushId, stats[statKey], unit)
        }
    }
}

function incrementUsageCounters(usage: MetricsUsageAccumulator): void {
    let bytesReceived = 0
    let recordsReceived = 0
    let bytesAllowed = 0
    let recordsAllowed = 0
    for (const [teamId, stats] of usage.entries()) {
        bytesReceived += stats.bytesReceived
        recordsReceived += stats.recordsReceived
        bytesAllowed += stats.bytesAllowed
        recordsAllowed += stats.recordsAllowed
        const teamIdLabel = teamId.toString()
        if (stats.bytesDropped > 0) {
            metricsBytesDroppedCounter.inc({ team_id: teamIdLabel }, stats.bytesDropped)
        }
        if (stats.recordsDropped > 0) {
            metricsRecordsDroppedCounter.inc({ team_id: teamIdLabel }, stats.recordsDropped)
        }
    }
    metricsBytesReceivedCounter.inc(bytesReceived)
    metricsRecordsReceivedCounter.inc(recordsReceived)
    metricsBytesAllowedCounter.inc(bytesAllowed)
    metricsRecordsAllowedCounter.inc(recordsAllowed)
}

async function emitUsageRows(
    outputs: IngestionOutputs<AppMetricsOutput>,
    usage: MetricsUsageAccumulator
): Promise<void> {
    const aggregator = new AppMetricsAggregator(outputs)
    for (const [teamId, stats] of usage.entries()) {
        for (const [statKey, metricName] of USAGE_METRIC_NAMES) {
            const count = stats[statKey]
            if (count === 0) {
                continue
            }
            aggregator.queue({
                team_id: teamId,
                app_source: 'metrics',
                app_source_id: '',
                instance_id: '',
                metric_kind: 'usage',
                metric_name: metricName,
                count,
            })
        }
    }

    try {
        await aggregator.flush()
    } catch (error) {
        logger.error('🔴', 'Failed to emit usage metrics - billing data may be lost', { error })
    }
}

/** Never rejects. A failed write of the billing rows is logged. */
export async function emitMetricsUsage(
    outputs: IngestionOutputs<AppMetricsOutput>,
    usageBatch: UsageRecordBatch,
    usage: MetricsUsageAccumulator
): Promise<void> {
    incrementUsageCounters(usage)
    addMetricsUsageRecords(usageBatch, usage.entries())
    await Promise.all([
        emitUsageRows(outputs, usage),
        usageBatch.flush().catch((error) => {
            logger.error('🔴', 'Failed to emit usage records - billing data may be lost', { error })
        }),
    ])
}

export function createKeepMetricsUsageStep<T extends { batchContext: MetricsUsageBatchContext }>(): ProcessingStep<
    T,
    T
> {
    return function keepMetricsUsageStep(input) {
        return Promise.resolve(ok(input))
    }
}
